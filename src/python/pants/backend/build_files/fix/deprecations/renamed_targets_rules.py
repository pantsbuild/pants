# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import tokenize
from dataclasses import dataclass

from pants.backend.build_files.fix.base import FixBuildFilesRequest
from pants.backend.build_files.fix.deprecations.base import FixBUILDFileRequest, FixedBUILDFile
from pants.backend.build_files.fix.deprecations.subsystem import BUILDDeprecationsFixer
from pants.core.goals.fix import FixResult
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import digest_to_snapshot, directory_digest_to_digest_contents
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import RegisteredTargetTypes
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


class RenameTargetsInFilesRequest(FixBuildFilesRequest):
    tool_subsystem = BUILDDeprecationsFixer


class RenameTargetsInFileRequest(FixBUILDFileRequest):
    """Deprecated target type names to new names."""


@dataclass(frozen=True)
class RenamedTargetTypes:
    """Map deprecated field names to their new name, per target."""

    target_renames: FrozenDict[str, str]


@rule
def determine_renamed_target_types(
    target_types: RegisteredTargetTypes,
) -> RenamedTargetTypes:
    return RenamedTargetTypes(
        FrozenDict(
            {
                tgt.deprecated_alias: tgt.alias
                for tgt in target_types.types
                if tgt.deprecated_alias is not None
            }
        )
    )


@rule
def fix_single(
    request: RenameTargetsInFileRequest,
    renamed_target_types: RenamedTargetTypes,
) -> FixedBUILDFile:
    tokens = request.tokenize()

    def should_be_renamed(token: tokenize.TokenInfo) -> bool:
        no_indentation = token.start[1] == 0
        if not (
            token.type is tokenize.NAME
            and token.string in renamed_target_types.target_renames
            and no_indentation
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
        line = updated_text_lines[line_index]
        suffix = line[token.end[1] :]
        new_symbol = renamed_target_types.target_renames[token.string]
        updated_text_lines[line_index] = f"{new_symbol}{suffix}"

    return FixedBUILDFile(request.path, content="".join(updated_text_lines).encode("utf-8"))


@rule(desc="Fix deprecated target type names", level=LogLevel.DEBUG)
async def fix(
    request: RenameTargetsInFilesRequest.Batch,
) -> FixResult:
    digest_contents = await directory_digest_to_digest_contents(request.snapshot.digest)
    fixed_contents = await concurrently(
        fix_single(
            RenameTargetsInFileRequest(file_content.path, file_content.content), **implicitly()
        )
        for file_content in digest_contents
    )
    snapshot = await digest_to_snapshot(
        **implicitly(
            CreateDigest(FileContent(content.path, content.content) for content in fixed_contents)
        )
    )
    return FixResult(
        request.snapshot, snapshot, "", "", tool_name=RenameTargetsInFilesRequest.tool_name
    )


def rules():
    return [
        *collect_rules(),
        *RenameTargetsInFilesRequest.rules(),
    ]
