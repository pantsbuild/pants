# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os.path
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from typing import DefaultDict, cast

from colors import green, red

from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    PathGlobs,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.parser import ParseError
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.dirutil import recursive_dirname
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized

# ------------------------------------------------------------------------------------------
# Generic goal
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RewrittenBuildFile:
    path: str
    lines: tuple[str, ...]
    change_descriptions: tuple[str, ...]


@union
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
    help = (
        "Format and fix safe deprecations in BUILD files.\n\n"
        "This does not handle the full Pants upgrade. You must still manually change "
        "`pants_version` in `pants.toml` and you may need to manually address some deprecations. "
        f"See {doc_url('upgrade-tips')} for upgrade tips.\n\n"
        "This goal is run without arguments. It will run over all BUILD files in your "
        "project."
    )

    required_union_implementations = (RewrittenBuildFileRequest,)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--check",
            type=bool,
            default=False,
            help=(
                "Do not write changes to disk, only write back what would change. Return code "
                "0 means there would be no changes, and 1 means that there would be. "
            ),
        )
        register(
            "--fmt",
            type=bool,
            default=True,
            help=(
                "Format BUILD files using Black.\n\n"
                "Set `[black].args`, `[black].config`, and `[black].config_discovery` to change "
                "Black's behavior. Set `[black].interpreter_constraints` and "
                "`[python].interpreter_search_path` to change which interpreter is used to "
                "run Black."
            ),
        )
        register(
            "--fix-safe-deprecations",
            type=bool,
            default=True,
            help=(
                "Automatically fix deprecations, such as target type renames, that are safe "
                "because they do not change semantics."
            ),
        )

    @property
    def check(self) -> bool:
        return cast(bool, self.options.check)

    @property
    def fmt(self) -> bool:
        return cast(bool, self.options.fmt)

    @property
    def fix_safe_deprecations(self) -> bool:
        return cast(bool, self.options.fix_safe_deprecations)


class UpdateBuildFilesGoal(Goal):
    subsystem_cls = UpdateBuildFilesSubsystem


@goal_rule(desc="Update all BUILD files", level=LogLevel.DEBUG)
async def update_build_files(
    update_build_files_subsystem: UpdateBuildFilesSubsystem,
    build_file_options: BuildFileOptions,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> UpdateBuildFilesGoal:
    all_build_files = await Get(
        DigestContents,
        PathGlobs(
            globs=(
                *(os.path.join("**", p) for p in build_file_options.patterns),
                *(f"!{p}" for p in build_file_options.ignores),
            )
        ),
    )

    rewrite_request_classes = []
    for request in union_membership[RewrittenBuildFileRequest]:
        if issubclass(request, FormatWithBlackRequest):
            if update_build_files_subsystem.fmt:
                rewrite_request_classes.append(request)
            else:
                continue
        if update_build_files_subsystem.fix_safe_deprecations or not issubclass(
            request, DeprecationFixerRequest
        ):
            rewrite_request_classes.append(request)

    build_file_to_lines = {
        build_file.path: tuple(build_file.content.decode("utf-8").splitlines())
        for build_file in all_build_files
    }
    build_file_to_change_descriptions: DefaultDict[str, list[str]] = defaultdict(list)
    for rewrite_request_cls in rewrite_request_classes:
        all_rewritten_files = await MultiGet(
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
        console.print_stderr(
            "No required changes to BUILD files found.\n\n"
            "Note that there may still be deprecations this goal doesn't know how to fix. See "
            f"{doc_url('upgrade-tips')} for upgrade tips."
        )
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

    return UpdateBuildFilesGoal(exit_code=1 if update_build_files_subsystem.check else 0)


# ------------------------------------------------------------------------------------------
# Black formatter fixer
# ------------------------------------------------------------------------------------------


class FormatWithBlackRequest(RewrittenBuildFileRequest):
    pass


@rule
async def format_build_file_with_black(
    request: FormatWithBlackRequest, black: Black
) -> RewrittenBuildFile:
    black_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="black.pex",
            internal_only=True,
            requirements=black.pex_requirements(),
            interpreter_constraints=black.interpreter_constraints,
            main=black.main,
        ),
    )
    build_file_digest_get = Get(Digest, CreateDigest([request.to_file_content()]))
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, black.config_request(recursive_dirname(request.path))
    )
    black_pex, build_file_digest, config_files = await MultiGet(
        black_pex_get, build_file_digest_get, config_files_get
    )

    input_digest = await Get(
        Digest, MergeDigests((build_file_digest, config_files.snapshot.digest))
    )

    argv = []
    if black.config:
        argv.extend(["--config", black.config])
    argv.extend(black.args)
    argv.append(request.path)

    black_result = await Get(
        ProcessResult,
        VenvPexProcess(
            black_pex,
            argv=argv,
            input_digest=input_digest,
            output_files=(request.path,),
            description=f"Run Black on {request.path}.",
            level=LogLevel.DEBUG,
        ),
    )

    if black_result.output_digest == build_file_digest:
        return RewrittenBuildFile(request.path, request.lines, change_descriptions=())

    result_contents = await Get(DigestContents, Digest, black_result.output_digest)
    assert len(result_contents) == 1
    result_lines = tuple(result_contents[0].content.decode("utf-8").splitlines())
    return RewrittenBuildFile(
        request.path, result_lines, change_descriptions=("Format with Black",)
    )


# ------------------------------------------------------------------------------------------
# Rename deprecated target types fixer
# ------------------------------------------------------------------------------------------


class RenameDeprecatedTargetsRequest(DeprecationFixerRequest):
    pass


class RenamedTargetTypes(FrozenDict[str, str]):
    """Deprecated target type names to new names."""


@rule
def determine_renamed_target_types(target_types: RegisteredTargetTypes) -> RenamedTargetTypes:
    return RenamedTargetTypes(
        {
            tgt.deprecated_alias: tgt.alias
            for tgt in target_types.types
            if tgt.deprecated_alias is not None
        }
    )


@rule(desc="Check for deprecated target type names", level=LogLevel.DEBUG)
def maybe_rename_deprecated_targets(
    request: RenameDeprecatedTargetsRequest,
    renamed_target_types: RenamedTargetTypes,
) -> RewrittenBuildFile:
    tokens = request.tokenize()
    applied_renames: set[tuple[str, str]] = set()

    def should_be_renamed(token: tokenize.TokenInfo) -> bool:
        no_indentation = token.start[1] == 0
        if not (
            token.type is tokenize.NAME and token.string in renamed_target_types and no_indentation
        ):
            return False
        # Ensure that the next token is `(`
        try:
            next_token = tokens[tokens.index(token) + 1]
        except IndexError:
            return False
        return next_token.type is tokenize.OP and next_token.string == "("

    updated_text_lines = list(request.lines)
    for token in tokens:
        if not should_be_renamed(token):
            continue
        line_index = token.start[0] - 1
        line = request.lines[line_index]
        suffix = line[token.end[1] :]
        new_symbol = renamed_target_types[token.string]
        applied_renames.add((token.string, new_symbol))
        updated_text_lines[line_index] = f"{new_symbol}{suffix}"

    return RewrittenBuildFile(
        request.path,
        tuple(updated_text_lines),
        change_descriptions=tuple(
            f"Rename `{request.red(deprecated)}` to `{request.green(new)}`"
            for deprecated, new in sorted(applied_renames)
        ),
    )


def rules():
    return (
        *collect_rules(),
        *pex.rules(),
        UnionRule(RewrittenBuildFileRequest, RenameDeprecatedTargetsRequest),
        # NB: We want this to come at the end so that running Black happens after all our
        # deprecation fixers.
        UnionRule(RewrittenBuildFileRequest, FormatWithBlackRequest),
    )
