# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import tokenize
from io import BytesIO

from pants.base.specs import Specs
from pants.core.goals.tailor import specs_to_dirs
from pants.engine.console import Console
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, PathGlobs, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import RegisteredTargetTypes
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel


class MendSubsystem(GoalSubsystem):
    name = "mend"
    help = "Automate fixing Pants deprecations."


class MendGoal(Goal):
    subsystem_cls = MendSubsystem


@goal_rule(desc="Automate fixing Pants deprecations", level=LogLevel.DEBUG)
async def run_mend(
    build_file_options: BuildFileOptions,
    console: Console,
    workspace: Workspace,
    specs: Specs,
    registered_target_types: RegisteredTargetTypes,
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

    # TODO: Decide how to handle if any fixers need to be AST-based. Do we switch everything to
    #  AST, or somehow pipe tokenizer-based fixers into AST-based ones?
    try:
        build_files_to_tokens_and_lines = {
            build_file.path: (
                list(tokenize.tokenize(BytesIO(build_file.content).readline)),
                tuple(build_file.content.decode("utf-8").splitlines()),
            )
            for build_file in all_build_files
        }
    except tokenize.TokenError:
        # If a BUILD file can't be fixed, we simply ignore it for now. The user can still manually
        # fix that file.
        #
        # This behavior can be changed to error or warn if that seems useful.
        return MendGoal(exit_code=1)

    renamed_target_types = {
        tgt.deprecated_alias: tgt.alias
        for tgt in registered_target_types.types
        if tgt.deprecated_alias is not None
    }

    # TODO: Allow piping a fixer into another one.
    updated_build_files = {}
    for path, (tokens, lines) in build_files_to_tokens_and_lines.items():
        possibly_new_build = maybe_rename_deprecated_targets(renamed_target_types, lines, tokens)
        if possibly_new_build is not None:
            updated_build_files[path] = possibly_new_build

    if not updated_build_files:
        console.print_stdout(
            "No required changes found. Note that there may still be deprecations this goal "
            f"doesn't know how to fix. See {doc_url('upgrade-tips')} for upgrade tips."
        )
        return MendGoal(exit_code=0)

    result = await Get(
        Digest,
        CreateDigest(
            FileContent(path, ("\n".join(new_content) + "\n").encode("utf-8"))
            for path, new_content in updated_build_files.items()
        ),
    )
    workspace.write_digest(result)

    for updated_build_file in updated_build_files:
        console.print_stdout(f"Updated {console.blue(updated_build_file)}:")
        # TODO: Generalize this.
        console.print_stdout("  - Renamed deprecated target type names")
    return MendGoal(exit_code=0)


def maybe_rename_deprecated_targets(
    deprecated_tgt_name_to_rename: dict[str, str],
    original_lines: tuple[str, ...],
    tokens: list[tokenize.TokenInfo],
) -> tuple[str, ...] | None:
    def should_be_renamed(token: tokenize.TokenInfo) -> bool:
        no_indentation = token.start[1] == 0
        if not (
            token.type is tokenize.NAME
            and token.string in deprecated_tgt_name_to_rename
            and no_indentation
        ):
            return False
        # Ensure that the next token is `(`
        try:
            next_token = tokens[tokens.index(token) + 1]
        except IndexError:
            return False
        return next_token.type is tokenize.OP and next_token.string == "("

    updated_text_lines = list(original_lines)
    for token in tokens:
        if not should_be_renamed(token):
            continue
        line_index = token.start[0] - 1
        line = original_lines[line_index]
        suffix = line[token.end[1] :]
        new_symbol = deprecated_tgt_name_to_rename[token.string]
        updated_text_lines[line_index] = f"{new_symbol}{suffix}"

    result = tuple(updated_text_lines)
    return result if result != original_lines else None


def rules():
    return collect_rules()
