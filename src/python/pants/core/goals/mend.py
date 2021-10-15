# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from typing import DefaultDict

from pants.base.specs import Specs
from pants.core.goals.tailor import specs_to_dirs
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, PathGlobs, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.parser import ParseError
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

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

    def debug_hint(self) -> str:
        return self.path

    def tokenize(self) -> list[tokenize.TokenInfo]:
        _bytes_stream = BytesIO("\n".join(self.lines).encode("utf-8"))
        try:
            return list(tokenize.tokenize(_bytes_stream.readline))
        except tokenize.TokenError as e:
            raise ParseError(f"Failed to parse {self.path}: {e}")


class MendSubsystem(GoalSubsystem):
    name = "mend"
    help = "Automate fixing Pants deprecations."

    required_union_implementations = (RewrittenBuildFileRequest,)


class MendGoal(Goal):
    subsystem_cls = MendSubsystem


@goal_rule(desc="Automate fixing Pants deprecations", level=LogLevel.DEBUG)
async def run_mend(
    build_file_options: BuildFileOptions,
    console: Console,
    workspace: Workspace,
    specs: Specs,
    union_membership: UnionMembership,
) -> MendGoal:
    all_build_files = await Get(
        DigestContents,
        PathGlobs(
            globs=(
                *(
                    os.path.join(dir_path, "**", p)
                    for dir_path in specs_to_dirs(specs)
                    for p in build_file_options.patterns
                ),
                *(f"!{p}" for p in build_file_options.ignores),
            )
        ),
    )

    build_file_to_lines = {
        build_file.path: tuple(build_file.content.decode("utf-8").splitlines())
        for build_file in all_build_files
    }
    build_file_to_change_descriptions: DefaultDict[str, list[str]] = defaultdict(list)
    for rewrite_request_cls in union_membership[RewrittenBuildFileRequest]:
        all_rewritten_files = await MultiGet(
            Get(
                RewrittenBuildFile,
                RewrittenBuildFileRequest,
                rewrite_request_cls(build_file, lines),
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

    changed_build_files = {
        build_file
        for build_file, change_descriptions in build_file_to_change_descriptions.items()
        if change_descriptions
    }
    if not changed_build_files:
        console.print_stdout(
            "No required changes to BUILD files found. Note that there may still be deprecations "
            f"this goal doesn't know how to fix. See {doc_url('upgrade-tips')} for upgrade tips."
        )
        return MendGoal(exit_code=0)

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
        console.print_stdout(f"Updated {console.blue(build_file)}:\n{formatted_changes}")

    return MendGoal(exit_code=0)


# ------------------------------------------------------------------------------------------
# Rename deprecated target types fixer
# ------------------------------------------------------------------------------------------


class RenameDeprecatedTargetsRequest(RewrittenBuildFileRequest):
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
        updated_text_lines[line_index] = f"{new_symbol}{suffix}"

    result_lines = tuple(updated_text_lines)
    return RewrittenBuildFile(
        request.path,
        result_lines,
        change_descriptions=(
            ("Renamed deprecated target type names",) if result_lines != request.lines else ()
        ),
    )


def rules():
    return (*collect_rules(), UnionRule(RewrittenBuildFileRequest, RenameDeprecatedTargetsRequest))
