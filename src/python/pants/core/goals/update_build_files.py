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
from typing import DefaultDict, Mapping, cast

from colors import green, red

from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.yapf.subsystem import Yapf
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
from pants.engine.target import RegisteredTargetTypes, TargetGenerator
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.option_types import BoolOption, EnumOption
from pants.util.dirutil import recursive_dirname
from pants.util.docutil import bin_name, doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized

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

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return RewrittenBuildFileRequest in union_membership

    check = BoolOption(
        "--check",
        default=False,
        help=(
            "Do not write changes to disk, only write back what would change. Return code "
            "0 means there would be no changes, and 1 means that there would be. "
        ),
    )
    fmt = BoolOption(
        "--fmt",
        default=True,
        help=(
            "Format BUILD files using Black or Yapf.\n\n"
            "Set `[black].args` / `[yapf].args`, `[black].config` / `[yapf].config` , "
            "and `[black].config_discovery` / `[yapf].config_discovery` to change "
            "Black's or Yapf's behavior. Set "
            "`[black].interpreter_constraints` / `[yapf].interpreter_constraints` "
            "and `[python].interpreter_search_path` to change which interpreter is "
            "used to run the formatter."
        ),
    )
    formatter = EnumOption(
        "--formatter",
        default=Formatter.BLACK,
        help="Which formatter Pants should use to format BUILD files.",
    )
    fix_safe_deprecations = BoolOption(
        "--fix-safe-deprecations",
        default=True,
        help=(
            "Automatically fix deprecations, such as target type renames, that are safe "
            "because they do not change semantics."
        ),
    )
    fix_python_macros = BoolOption(
        "--fix-python-macros",
        default=False,
        help="Deprecated.",
        removal_version="2.13.0.dev0",
        removal_hint=(
            "No longer does anything as the old macros have been removed in favor of target "
            "generators."
        ),
    )


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
        if issubclass(request, (FormatWithBlackRequest, FormatWithYapfRequest)):
            is_chosen_formatter = issubclass(request, FormatWithBlackRequest) ^ (
                update_build_files_subsystem.formatter == Formatter.YAPF
            )

            if update_build_files_subsystem.fmt and is_chosen_formatter:
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
        msg = "No required changes to BUILD files found."
        if not update_build_files_subsystem.check:
            msg += (
                " However, there may still be deprecations that `update-build-files` doesn't know "
                f"how to fix. See {doc_url('upgrade-tips')} for upgrade tips."
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
    yapf_pex_get = Get(VenvPex, PexRequest, yapf.to_pex_request())
    build_file_digest_get = Get(Digest, CreateDigest([request.to_file_content()]))
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, yapf.config_request(recursive_dirname(request.path))
    )
    yapf_pex, build_file_digest, config_files = await MultiGet(
        yapf_pex_get, build_file_digest_get, config_files_get
    )

    input_digest = await Get(
        Digest, MergeDigests((build_file_digest, config_files.snapshot.digest))
    )

    argv = ["--in-place"]
    if yapf.config:
        argv.extend(["--config", yapf.config])
    argv.extend(yapf.args)
    argv.append(request.path)

    yapf_result = await Get(
        ProcessResult,
        VenvPexProcess(
            yapf_pex,
            argv=argv,
            input_digest=input_digest,
            output_files=(request.path,),
            description=f"Run Yapf on {request.path}.",
            level=LogLevel.DEBUG,
        ),
    )

    if yapf_result.output_digest == build_file_digest:
        return RewrittenBuildFile(request.path, request.lines, change_descriptions=())

    result_contents = await Get(DigestContents, Digest, yapf_result.output_digest)
    assert len(result_contents) == 1
    result_lines = tuple(result_contents[0].content.decode("utf-8").splitlines())
    return RewrittenBuildFile(request.path, result_lines, change_descriptions=("Format with Yapf",))


# ------------------------------------------------------------------------------------------
# Black formatter fixer
# ------------------------------------------------------------------------------------------


class FormatWithBlackRequest(RewrittenBuildFileRequest):
    pass


@rule
async def format_build_file_with_black(
    request: FormatWithBlackRequest, black: Black
) -> RewrittenBuildFile:
    black_pex_get = Get(VenvPex, PexRequest, black.to_pex_request())
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


# ------------------------------------------------------------------------------------------
# Rename deprecated field types fixer
# ------------------------------------------------------------------------------------------


class RenameDeprecatedFieldsRequest(DeprecationFixerRequest):
    pass


@dataclass(frozen=True)
class RenamedFieldTypes:
    """Map deprecated field names to their new name, per target."""

    target_field_renames: FrozenDict[str, FrozenDict[str, str]]

    @classmethod
    def from_dict(cls, data: Mapping[str, Mapping[str, str]]) -> RenamedFieldTypes:
        return cls(
            FrozenDict(
                {
                    target_name: FrozenDict(
                        {
                            deprecated_field_name: new_field_name
                            for deprecated_field_name, new_field_name in field_renames.items()
                        }
                    )
                    for target_name, field_renames in data.items()
                }
            )
        )


@rule
def determine_renamed_field_types(
    target_types: RegisteredTargetTypes, union_membership: UnionMembership
) -> RenamedFieldTypes:
    target_field_renames: DefaultDict[str, dict[str, str]] = defaultdict(dict)
    for tgt in target_types.types:
        field_types = list(tgt.class_field_types(union_membership))
        if issubclass(tgt, TargetGenerator):
            field_types.extend(tgt.moved_fields)

        for field_type in field_types:
            if field_type.deprecated_alias is not None:
                target_field_renames[tgt.alias][field_type.deprecated_alias] = field_type.alias

        # Make sure we also update deprecated fields in deprecated targets.
        if tgt.deprecated_alias is not None:
            target_field_renames[tgt.deprecated_alias] = target_field_renames[tgt.alias]

    return RenamedFieldTypes.from_dict(target_field_renames)


@rule(desc="Check for deprecated field type names", level=LogLevel.DEBUG)
def maybe_rename_deprecated_fields(
    request: RenameDeprecatedFieldsRequest,
    renamed_field_types: RenamedFieldTypes,
) -> RewrittenBuildFile:
    pants_target: str = ""
    level: int = 0
    applied_renames: set[tuple[str, str, str]] = set()
    tokens = iter(request.tokenize())

    def parse_level(token: tokenize.TokenInfo) -> bool:
        """Returns true if token was consumed."""
        nonlocal level

        if level == 0 or token.type is not tokenize.OP or token.string not in ["(", ")"]:
            return False

        if token.string == "(":
            level += 1
        elif token.string == ")":
            level -= 1

        return True

    def parse_target(token: tokenize.TokenInfo) -> bool:
        """Returns true if we're parsing a field name for a top level target."""
        nonlocal pants_target
        nonlocal level

        if parse_level(token):
            # Consumed parenthesis operator.
            return False

        if token.type is not tokenize.NAME:
            return False

        if level == 0 and next_token_is("("):
            level = 1
            pants_target = token.string
            # Current token consumed.
            return False

        return level == 1

    def next_token_is(string: str, token_type=tokenize.OP) -> bool:
        for next_token in tokens:
            if next_token.type is tokenize.NL:
                continue
            parse_level(next_token)
            return next_token.type is token_type and next_token.string == string
        return False

    def should_be_renamed(token: tokenize.TokenInfo) -> bool:
        nonlocal pants_target

        if not parse_target(token):
            return False

        if pants_target not in renamed_field_types.target_field_renames:
            return False

        return (
            next_token_is("=")
            and token.string in renamed_field_types.target_field_renames[pants_target]
        )

    updated_text_lines = list(request.lines)
    for token in tokens:
        if not should_be_renamed(token):
            continue
        line_index = token.start[0] - 1
        line = request.lines[line_index]
        prefix = line[: token.start[1]]
        suffix = line[token.end[1] :]
        new_symbol = renamed_field_types.target_field_renames[pants_target][token.string]
        applied_renames.add((pants_target, token.string, new_symbol))
        updated_text_lines[line_index] = f"{prefix}{new_symbol}{suffix}"

    return RewrittenBuildFile(
        request.path,
        tuple(updated_text_lines),
        change_descriptions=tuple(
            f"Rename the field `{request.red(deprecated)}` to `{request.green(new)}` for target type `{target}`"
            for target, deprecated, new in sorted(applied_renames)
        ),
    )


def rules():
    return (
        *collect_rules(),
        *pex.rules(),
        UnionRule(RewrittenBuildFileRequest, RenameDeprecatedTargetsRequest),
        UnionRule(RewrittenBuildFileRequest, RenameDeprecatedFieldsRequest),
        # NB: We want this to come at the end so that running Black or Yapf happens
        # after all our deprecation fixers.
        UnionRule(RewrittenBuildFileRequest, FormatWithBlackRequest),
        UnionRule(RewrittenBuildFileRequest, FormatWithYapfRequest),
    )
