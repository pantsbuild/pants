# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os.path
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from typing import DefaultDict, cast

from colors import green, red

from pants.backend.build_files.fix.deprecations import renamed_fields_rules, renamed_targets_rules
from pants.backend.build_files.fix.deprecations.base import FixedBUILDFile
from pants.backend.build_files.fmt.black.register import BlackRequest
from pants.backend.build_files.fmt.ruff.register import RuffRequest
from pants.backend.build_files.fmt.yapf.register import YapfRequest
from pants.backend.python.goals import lockfile
from pants.backend.python.lint.black.rules import _run_black
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.ruff.fmt_rules import _run_ruff_fmt
from pants.backend.python.lint.ruff.subsystem import Ruff
from pants.backend.python.lint.yapf.rules import _run_yapf
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.subsystems.python_tool_base import get_lockfile_interpreter_constraints
from pants.backend.python.util_rules import pex
from pants.base.specs import Specs
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    PathGlobs,
    Paths,
    Snapshot,
    SpecsPaths,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.parser import ParseError
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.option_types import BoolOption, EnumOption
from pants.util.docutil import bin_name, doc_url
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.strutil import help_text, softwrap

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------
# Generic goal
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RewrittenBuildFile:
    path: str
    lines: tuple[str, ...]
    change_descriptions: tuple[str, ...]


class Formatter(Enum):
    YAPF = "yapf"
    BLACK = "black"
    RUFF = "ruff"


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class RewrittenBuildFileRequest(EngineAwareParameter):
    path: str
    lines: tuple[str, ...]
    colors_enabled: bool = dataclasses.field(compare=False)

    def debug_hint(self) -> str:
        return self.path

    def to_file_content(self) -> FileContent:
        lines = "\n".join(self.lines) + "\n"
        return FileContent(self.path, lines.encode("utf-8"))

    @memoized
    def tokenize(self) -> list[tokenize.TokenInfo]:
        _bytes_stream = BytesIO("\n".join(self.lines).encode("utf-8"))
        try:
            return list(tokenize.tokenize(_bytes_stream.readline))
        except tokenize.TokenError as e:
            raise ParseError(f"Failed to parse {self.path}: {e}")

    def red(self, s: str) -> str:
        return cast(str, red(s)) if self.colors_enabled else s

    def green(self, s: str) -> str:
        return cast(str, green(s)) if self.colors_enabled else s


class DeprecationFixerRequest(RewrittenBuildFileRequest):
    """A fixer for deprecations.

    These can be disabled by the user with `--no-fix-safe-deprecations`.
    """


class UpdateBuildFilesSubsystem(GoalSubsystem):
    name = "update-build-files"
    help = help_text(
        f"""
        Format and fix safe deprecations in BUILD files.

        This does not handle the full Pants upgrade. You must still manually change
        `pants_version` in `pants.toml` and you may need to manually address some deprecations.
        See {doc_url('docs/releases/upgrade-tips')} for upgrade tips.

        This goal is run without arguments. It will run over all BUILD files in your
        project.
        """
    )

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return RewrittenBuildFileRequest in union_membership

    check = BoolOption(
        default=False,
        help=softwrap(
            """
            Do not write changes to disk, only write back what would change. Return code
            0 means there would be no changes, and 1 means that there would be.
            """
        ),
    )
    fmt = BoolOption(
        default=True,
        help=softwrap(
            """
            Format BUILD files using Black, Ruff or Yapf.

            Set `[black].args` / `[ruff].args` / `[yapf].args`, `[black].config` / `[ruff].config`, `[yapf].config` ,
            and `[black].config_discovery` / `[ruff].config_discovery`, `[yapf].config_discovery` to change
            Black's, Ruff's, or Yapf's behavior. Set
            `[black].interpreter_constraints` / `[ruff].interpreter_constraints` / `[yapf].interpreter_constraints`
            and `[python].interpreter_search_path` to change which interpreter is
            used to run the formatter.
            """
        ),
    )
    formatter = EnumOption(
        default=Formatter.BLACK,
        help="Which formatter Pants should use to format BUILD files.",
    )
    fix_safe_deprecations = BoolOption(
        default=True,
        help=softwrap(
            """
            Automatically fix deprecations, such as target type renames, that are safe
            because they do not change semantics.
            """
        ),
    )


class UpdateBuildFilesGoal(Goal):
    subsystem_cls = UpdateBuildFilesSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule(desc="Update all BUILD files", level=LogLevel.DEBUG)
async def update_build_files(
    update_build_files_subsystem: UpdateBuildFilesSubsystem,
    build_file_options: BuildFileOptions,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
    specs: Specs,
) -> UpdateBuildFilesGoal:
    if not specs:
        if not specs.includes.from_change_detection:
            logger.warning(
                softwrap(
                    f"""\
                    No arguments specified with `{bin_name()} update-build-files`, so the goal will
                    do nothing.

                    Instead, you should provide arguments like this:

                      * `{bin_name()} update-build-files ::` to run on everything
                      * `{bin_name()} update-build-files dir::` to run on `dir` and subdirs
                      * `{bin_name()} update-build-files dir` to run on `dir`
                      * `{bin_name()} update-build-files dir/BUILD` to run on that single BUILD file
                      * `{bin_name()} --changed-since=HEAD update-build-files` to run only on changed BUILD files
                    """
                )
            )
        return UpdateBuildFilesGoal(exit_code=0)

    all_build_file_paths, specs_paths = await MultiGet(
        Get(
            Paths,
            PathGlobs(
                globs=(
                    *(os.path.join("**", p) for p in build_file_options.patterns),
                    *(f"!{p}" for p in build_file_options.ignores),
                )
            ),
        ),
        Get(SpecsPaths, Specs, specs),
    )
    specified_paths = set(specs_paths.files)
    specified_build_files = await Get(
        DigestContents,
        PathGlobs(fp for fp in all_build_file_paths.files if fp in specified_paths),
    )

    rewrite_request_classes = []
    formatter_to_request_class: dict[Formatter, type[RewrittenBuildFileRequest]] = {
        Formatter.BLACK: FormatWithBlackRequest,
        Formatter.YAPF: FormatWithYapfRequest,
        Formatter.RUFF: FormatWithRuffRequest,
    }
    chosen_formatter_request_class = formatter_to_request_class.get(
        update_build_files_subsystem.formatter
    )
    if not chosen_formatter_request_class:
        raise ValueError(f"Unrecognized formatter: {update_build_files_subsystem.formatter}")

    for request in union_membership[RewrittenBuildFileRequest]:
        if update_build_files_subsystem.fmt and issubclass(request, chosen_formatter_request_class):
            rewrite_request_classes.append(request)

        if update_build_files_subsystem.fix_safe_deprecations or not issubclass(
            request, DeprecationFixerRequest
        ):
            rewrite_request_classes.append(request)

    build_file_to_lines = {
        build_file.path: tuple(build_file.content.decode("utf-8").splitlines())
        for build_file in specified_build_files
    }
    build_file_to_change_descriptions: DefaultDict[str, list[str]] = defaultdict(list)
    for rewrite_request_cls in rewrite_request_classes:
        all_rewritten_files = await MultiGet(  # noqa: PNT30: this is inherently sequential
            Get(
                RewrittenBuildFile,
                RewrittenBuildFileRequest,
                rewrite_request_cls(build_file, lines, colors_enabled=console._use_colors),
            )
            for build_file, lines in build_file_to_lines.items()
        )
        for rewritten_file in all_rewritten_files:
            if not rewritten_file.change_descriptions:
                continue
            build_file_to_lines[rewritten_file.path] = rewritten_file.lines
            build_file_to_change_descriptions[rewritten_file.path].extend(
                rewritten_file.change_descriptions
            )

    changed_build_files = sorted(
        build_file
        for build_file, change_descriptions in build_file_to_change_descriptions.items()
        if change_descriptions
    )
    if not changed_build_files:
        msg = "No required changes to BUILD files found."
        if not update_build_files_subsystem.check:
            msg += softwrap(
                f"""
                However, there may still be deprecations that `update-build-files` doesn't know
                how to fix. See {doc_url('docs/releases/upgrade-tips')} for upgrade tips.
                """
            )
        logger.info(msg)
        return UpdateBuildFilesGoal(exit_code=0)

    if not update_build_files_subsystem.check:
        result = await Get(
            Digest,
            CreateDigest(
                FileContent(
                    build_file, ("\n".join(build_file_to_lines[build_file]) + "\n").encode("utf-8")
                )
                for build_file in changed_build_files
            ),
        )
        workspace.write_digest(result)

    for build_file in changed_build_files:
        formatted_changes = "\n".join(
            f"  - {description}" for description in build_file_to_change_descriptions[build_file]
        )
        tense = "Would update" if update_build_files_subsystem.check else "Updated"
        console.print_stdout(f"{tense} {console.blue(build_file)}:\n{formatted_changes}")

    if update_build_files_subsystem.check:
        console.print_stdout(
            f"\nTo fix `update-build-files` failures, run `{bin_name()} update-build-files`."
        )

    return UpdateBuildFilesGoal(exit_code=1 if update_build_files_subsystem.check else 0)


# ------------------------------------------------------------------------------------------
# Yapf formatter fixer
# ------------------------------------------------------------------------------------------


class FormatWithYapfRequest(RewrittenBuildFileRequest):
    pass


@rule
async def format_build_file_with_yapf(
    request: FormatWithYapfRequest, yapf: Yapf
) -> RewrittenBuildFile:
    input_snapshot = await Get(Snapshot, CreateDigest([request.to_file_content()]))
    yapf_ics = await get_lockfile_interpreter_constraints(yapf)
    result = await _run_yapf(
        YapfRequest.Batch(
            Yapf.options_scope,
            input_snapshot.files,
            partition_metadata=None,
            snapshot=input_snapshot,
        ),
        yapf,
        yapf_ics,
    )
    output_content = await Get(DigestContents, Digest, result.output.digest)

    formatted_build_file_content = next(fc for fc in output_content if fc.path == request.path)
    build_lines = tuple(formatted_build_file_content.content.decode("utf-8").splitlines())
    change_descriptions = ("Format with Yapf",) if result.did_change else ()

    return RewrittenBuildFile(request.path, build_lines, change_descriptions=change_descriptions)


# ------------------------------------------------------------------------------------------
# Black formatter fixer
# ------------------------------------------------------------------------------------------


class FormatWithBlackRequest(RewrittenBuildFileRequest):
    pass


@rule
async def format_build_file_with_black(
    request: FormatWithBlackRequest, black: Black
) -> RewrittenBuildFile:
    input_snapshot = await Get(Snapshot, CreateDigest([request.to_file_content()]))
    black_ics = await get_lockfile_interpreter_constraints(black)
    result = await _run_black(
        BlackRequest.Batch(
            Black.options_scope,
            input_snapshot.files,
            partition_metadata=None,
            snapshot=input_snapshot,
        ),
        black,
        black_ics,
    )
    output_content = await Get(DigestContents, Digest, result.output.digest)

    formatted_build_file_content = next(fc for fc in output_content if fc.path == request.path)
    build_lines = tuple(formatted_build_file_content.content.decode("utf-8").splitlines())
    change_descriptions = ("Format with Black",) if result.did_change else ()

    return RewrittenBuildFile(request.path, build_lines, change_descriptions=change_descriptions)


# ------------------------------------------------------------------------------------------
# Ruff formatter fixer
# ------------------------------------------------------------------------------------------


class FormatWithRuffRequest(RewrittenBuildFileRequest):
    pass


@rule
async def format_build_file_with_ruff(
    request: FormatWithRuffRequest, ruff: Ruff
) -> RewrittenBuildFile:
    input_snapshot = await Get(Snapshot, CreateDigest([request.to_file_content()]))
    ruff_ics = await get_lockfile_interpreter_constraints(ruff)
    result = await _run_ruff_fmt(
        RuffRequest.Batch(
            Ruff.options_scope,
            input_snapshot.files,
            partition_metadata=None,
            snapshot=input_snapshot,
        ),
        ruff,
        ruff_ics,
    )
    output_content = await Get(DigestContents, Digest, result.output.digest)

    formatted_build_file_content = next(fc for fc in output_content if fc.path == request.path)
    build_lines = tuple(formatted_build_file_content.content.decode("utf-8").splitlines())
    change_descriptions = ("Format with Ruff",) if result.did_change else ()

    return RewrittenBuildFile(request.path, build_lines, change_descriptions=change_descriptions)


# ------------------------------------------------------------------------------------------
# Rename deprecated target types fixer
# ------------------------------------------------------------------------------------------


class RenameDeprecatedTargetsRequest(DeprecationFixerRequest):
    pass


@rule(desc="Check for deprecated target type names", level=LogLevel.DEBUG)
async def maybe_rename_deprecated_targets(
    request: RenameDeprecatedTargetsRequest,
) -> RewrittenBuildFile:
    old_bytes = "\n".join(request.lines).encode("utf-8")
    new_content = await Get(
        FixedBUILDFile,
        renamed_targets_rules.RenameTargetsInFileRequest(path=request.path, content=old_bytes),
    )

    return RewrittenBuildFile(
        request.path,
        tuple(new_content.content.decode("utf-8").splitlines()),
        change_descriptions=("Renamed deprecated targets",)
        if old_bytes != new_content.content
        else (),
    )


# ------------------------------------------------------------------------------------------
# Rename deprecated field types fixer
# ------------------------------------------------------------------------------------------


class RenameDeprecatedFieldsRequest(DeprecationFixerRequest):
    pass


@rule(desc="Check for deprecated field type names", level=LogLevel.DEBUG)
async def maybe_rename_deprecated_fields(
    request: RenameDeprecatedFieldsRequest,
) -> RewrittenBuildFile:
    old_bytes = "\n".join(request.lines).encode("utf-8")
    new_content = await Get(
        FixedBUILDFile,
        renamed_fields_rules.RenameFieldsInFileRequest(path=request.path, content=old_bytes),
    )

    return RewrittenBuildFile(
        request.path,
        tuple(new_content.content.decode("utf-8").splitlines()),
        change_descriptions=("Renamed deprecated fields",)
        if old_bytes != new_content.content
        else (),
    )


def rules():
    return (
        *collect_rules(),
        *collect_rules(renamed_fields_rules),
        *collect_rules(renamed_targets_rules),
        *pex.rules(),
        *lockfile.rules(),
        UnionRule(RewrittenBuildFileRequest, RenameDeprecatedTargetsRequest),
        UnionRule(RewrittenBuildFileRequest, RenameDeprecatedFieldsRequest),
        # NB: We want this to come at the end so that running Black or Yapf happens
        # after all our deprecation fixers.
        UnionRule(RewrittenBuildFileRequest, FormatWithBlackRequest),
        UnionRule(RewrittenBuildFileRequest, FormatWithYapfRequest),
        UnionRule(RewrittenBuildFileRequest, FormatWithRuffRequest),
    )
