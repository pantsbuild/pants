# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from typing_extensions import assert_never

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.backend.sql.lint.sqlfluff.subsystem import Sqlfluff, SqlfluffFieldSet, SqlfluffMode
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.fs import MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.intrinsics import (
    merge_digests_request_to_digest,
    process_request_to_process_result,
)
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Rule, collect_rules, concurrently, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import pluralize


class SqlfluffFixRequest(FixTargetsRequest):
    field_set_type = SqlfluffFieldSet
    tool_subsystem = Sqlfluff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    # We don't need to include automatically added lint rules for this SqlfluffFixRequest,
    # because these lint rules are already checked by SqlfluffLintRequest.
    enable_lint_rules = False


class SqlfluffLintRequest(LintTargetsRequest):
    field_set_type = SqlfluffFieldSet
    tool_subsystem = Sqlfluff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


class SqlfluffFormatRequest(FmtTargetsRequest):
    field_set_type = SqlfluffFieldSet
    tool_subsystem = Sqlfluff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    @classproperty
    def tool_name(cls) -> str:
        return "sqlfluff format"

    @classproperty
    def tool_id(cls) -> str:
        return "sqlfluff-format"


@dataclass(frozen=True)
class _RunSqlfluffRequest:
    snapshot: Snapshot
    mode: SqlfluffMode


async def run_sqlfluff(
    request: _RunSqlfluffRequest,
    sqlfluff: Sqlfluff,
) -> FallibleProcessResult:
    sqlfluff_pex_get = create_venv_pex(**implicitly({sqlfluff.to_pex_request(): PexRequest}))
    config_files_get = find_config_file(sqlfluff.config_request(request.snapshot.dirs))
    sqlfluff_pex, config_files = await concurrently(sqlfluff_pex_get, config_files_get)
    input_digest = await merge_digests_request_to_digest(
        MergeDigests((request.snapshot.digest, config_files.snapshot.digest))
    )

    initial_args: Tuple[str, ...] = ()
    if request.mode is SqlfluffMode.FMT:
        initial_args = ("format",)
    elif request.mode is SqlfluffMode.FIX:
        initial_args = ("fix", *sqlfluff.fix_args)
    elif request.mode is SqlfluffMode.LINT:
        initial_args = ("lint",)
    else:
        assert_never(request.mode)

    conf_args = ["--config", sqlfluff.config] if sqlfluff.config else []

    result = await process_request_to_process_result(
        **implicitly(
            VenvPexProcess(
                sqlfluff_pex,
                argv=(*initial_args, *conf_args, *sqlfluff.args, *request.snapshot.files),
                input_digest=input_digest,
                output_files=request.snapshot.files,
                description=f"Run sqlfluff {' '.join(initial_args)} on {pluralize(len(request.snapshot.files), 'file')}.",
                level=LogLevel.DEBUG,
            )
        )
    )
    return result


@rule(desc="Fix with sqlfluff fix", level=LogLevel.DEBUG)
async def sqlfluff_fix(request: SqlfluffFixRequest.Batch, sqlfluff: Sqlfluff) -> FixResult:
    result = await run_sqlfluff(
        _RunSqlfluffRequest(snapshot=request.snapshot, mode=SqlfluffMode.FIX), sqlfluff
    )
    return await FixResult.create(request, result)


@rule(desc="Lint with sqlfluff lint", level=LogLevel.DEBUG)
async def sqlfluff_lint(
    request: SqlfluffLintRequest.Batch[SqlfluffFieldSet, Any], sqlfluff: Sqlfluff
) -> LintResult:
    source_files = await determine_source_files(
        SourceFilesRequest(field_set.source for field_set in request.elements)
    )
    result = await run_sqlfluff(
        _RunSqlfluffRequest(snapshot=source_files.snapshot, mode=SqlfluffMode.LINT), sqlfluff
    )
    return LintResult.create(request, result)


@rule(desc="Format with sqlfluff format", level=LogLevel.DEBUG)
async def sqlfluff_fmt(request: SqlfluffFormatRequest.Batch, sqlfluff: Sqlfluff) -> FmtResult:
    result = await run_sqlfluff(
        _RunSqlfluffRequest(snapshot=request.snapshot, mode=SqlfluffMode.FMT), sqlfluff
    )
    return await FmtResult.create(request, result)


def rules() -> Iterable[Rule]:
    return (
        *collect_rules(),
        *SqlfluffLintRequest.rules(),
        *SqlfluffFixRequest.rules(),
        *SqlfluffFormatRequest.rules(),
        *pex.rules(),
    )
