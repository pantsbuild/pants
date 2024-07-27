# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import tokenize
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Mapping

from pants.backend.build_files.fix.base import FixBuildFilesRequest
from pants.backend.build_files.fix.deprecations.base import FixBUILDFileRequest, FixedBUILDFile
from pants.backend.build_files.fix.deprecations.subsystem import BUILDDeprecationsFixer
from pants.core.goals.fix import FixResult
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import digest_to_snapshot, directory_digest_to_digest_contents
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import RegisteredTargetTypes, TargetGenerator
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


class RenameFieldsInFilesRequest(FixBuildFilesRequest):
    tool_subsystem = BUILDDeprecationsFixer


class RenameFieldsInFileRequest(FixBUILDFileRequest):
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
                    target_name: FrozenDict(field_renames.items())
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


@rule
def fix_single(
    request: RenameFieldsInFileRequest,
    renamed_field_types: RenamedFieldTypes,
) -> FixedBUILDFile:
    pants_target: str = ""
    level: int = 0
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
        line = updated_text_lines[line_index]
        prefix = line[: token.start[1]]
        suffix = line[token.end[1] :]
        new_symbol = renamed_field_types.target_field_renames[pants_target][token.string]
        updated_text_lines[line_index] = f"{prefix}{new_symbol}{suffix}"

    return FixedBUILDFile(request.path, content="".join(updated_text_lines).encode("utf-8"))


@rule(desc="Fix deprecated field names", level=LogLevel.DEBUG)
async def fix(request: RenameFieldsInFilesRequest.Batch) -> FixResult:
    digest_contents = await directory_digest_to_digest_contents(request.snapshot.digest)
    fixed_contents = await concurrently(
        fix_single(
            RenameFieldsInFileRequest(file_content.path, file_content.content), **implicitly()
        )
        for file_content in digest_contents
    )
    snapshot = await digest_to_snapshot(
        **implicitly(
            CreateDigest(FileContent(content.path, content.content) for content in fixed_contents)
        )
    )
    return FixResult(
        request.snapshot, snapshot, "", "", tool_name=RenameFieldsInFilesRequest.tool_name
    )


def rules():
    return [
        *collect_rules(),
        *RenameFieldsInFilesRequest.rules(),
    ]
