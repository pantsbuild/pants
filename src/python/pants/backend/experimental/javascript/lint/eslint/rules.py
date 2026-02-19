# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""ESLint rules for JavaScript and TypeScript linting and formatting."""

from __future__ import annotations

import json
from collections.abc import Iterable

from pants.backend.experimental.javascript.lint.eslint.subsystem import (
    EslintFieldSet,
    EslintSubsystem,
)
from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.fs import MergeDigests
from pants.engine.intrinsics import execute_process, merge_digests
from pants.engine.process import FallibleProcessResult, execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

# NOTE: Previous code ran per-run npm installs for TS plugins. We now rely on
# extra dev dependencies declared in the subsystem for determinism & speed.


class EslintLintRequest(LintTargetsRequest):
    """Request for ESLint linting operations on JavaScript/TypeScript files."""

    field_set_type = EslintFieldSet
    tool_subsystem = EslintSubsystem
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


class EslintFmtRequest(FmtTargetsRequest):
    """Request for ESLint formatting operations."""

    field_set_type = EslintFieldSet
    tool_subsystem = EslintSubsystem
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Lint with ESLint", level=LogLevel.DEBUG)
async def eslint_lint(request: EslintLintRequest.Batch, eslint: EslintSubsystem) -> LintResult:
    if eslint.skip:
        return LintResult.noop()

    # Gather source files
    sources = await determine_source_files(
        SourceFilesRequest(field_set.sources for field_set in request.elements)
    )

    if not sources.files:
        return LintResult.noop()

    # Look for any/all of the ESLint configuration files
    config_files = await find_config_file(eslint.config_request(sources.snapshot.dirs))

    # Merge source files and config files
    input_digest = await merge_digests(
        MergeDigests(
            (
                sources.snapshot.digest,
                config_files.snapshot.digest,
            )
        )
    )

    # Build command arguments
    args_list: list[str] = []
    if eslint.config:
        args_list.extend(["--config", eslint.config])

    # Add user-specified arguments
    user_args = list(eslint.args)
    args_list.extend(user_args)

    wants_json = False
    if getattr(eslint, "json_output", False):
        # Only add json format if user did not already specify a formatter
        has_format = any(arg.startswith("--format") or arg == "-f" for arg in user_args)
        if not has_format:
            args_list.extend(["--format", "json"])
            wants_json = True

    # Add file paths
    args_list.extend(sources.files)
    args = tuple(args_list)

    # Execute ESLint
    result: FallibleProcessResult = await execute_process(
        **implicitly(
            {
                eslint.request(
                    args=args,
                    input_digest=input_digest,
                    description=f"Run ESLint on {pluralize(len(sources.files), 'file')}.",
                    level=LogLevel.DEBUG,
                ): NodeJSToolRequest
            }
        )
    )

    stdout = result.stdout.decode(errors="ignore")
    if wants_json:
        try:
            parsed = json.loads(stdout or "[]")
            if isinstance(parsed, list):
                errors = sum(
                    sum(1 for m in entry.get("messages", []) if m.get("severity") == 2)
                    for entry in parsed
                    if isinstance(entry, dict)
                )
                warnings = sum(
                    sum(1 for m in entry.get("messages", []) if m.get("severity") == 1)
                    for entry in parsed
                    if isinstance(entry, dict)
                )
                summary = f"ESLint summary: {errors} errors, {warnings} warnings\n\n"
                stdout = summary + stdout
        except Exception:
            pass

    return LintResult(
        exit_code=result.exit_code,
        stdout=stdout,
        stderr=result.stderr.decode(errors="ignore"),
        linter_name=request.tool_name,
        partition_description=request.partition_metadata.description,
    )


@rule(desc="Format with ESLint", level=LogLevel.DEBUG)
async def eslint_fmt(request: EslintFmtRequest.Batch, eslint: EslintSubsystem) -> FmtResult:
    if eslint.skip:
        return FmtResult.skip(request)

    # Look for any/all of the ESLint configuration files
    config_files = await find_config_file(eslint.config_request(request.snapshot.dirs))

    # Merge source files, config files, and eslint tool process
    input_digest = await merge_digests(
        MergeDigests(
            (
                request.snapshot.digest,
                config_files.snapshot.digest,
            )
        )
    )

    result = await execute_process_or_raise(
        **implicitly(
            {
                eslint.request(
                    args=(
                        "--fix",
                        *(("--config", eslint.config) if eslint.config else ()),
                        *eslint.args,
                        *request.files,
                    ),
                    input_digest=input_digest,
                    output_files=request.files,
                    description=f"Run ESLint --fix on {pluralize(len(request.files), 'file')}.",
                    level=LogLevel.DEBUG,
                ): NodeJSToolRequest
            }
        )
    )
    return await FmtResult.create(request, result)


def rules() -> Iterable[Rule | UnionRule]:
    """Return all rules provided by this module.

    Returns:
    Iterable of Rule and UnionRule objects for ESLint linting & formatting,
        including dependencies from nodejs_tool subsystem.
    """
    return (
        *collect_rules(),
        *nodejs_tool.rules(),
        *EslintLintRequest.rules(),
        *EslintFmtRequest.rules(),
    )
