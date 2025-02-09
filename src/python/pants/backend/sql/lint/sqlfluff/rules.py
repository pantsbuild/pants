# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Generic, Iterable, Iterator, Sequence, Tuple, TypeVar

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.core.goals.fix import FixResult, FixTargetsRequest, Partitions
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.partitions import Partition, PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.collection import Collection
from pants.engine.fs import Digest, DigestContents, FileContent, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.intrinsics import execute_process, merge_digests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, Rule, collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSet
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import pluralize
from typing_extensions import assert_never

from pants.backend.sql.lint.sqlfluff.subsystem import Sqlfluff, SqlfluffFieldSet, SqlfluffMode

logger = logging.getLogger(__name__)


class SqlfluffFixRequest(FixTargetsRequest):
    field_set_type = SqlfluffFieldSet
    tool_subsystem = Sqlfluff
    partitioner_type = PartitionerType.CUSTOM

    # We don't need to include automatically added lint rules for this SqlfluffFixRequest,
    # because these lint rules are already checked by SqlfluffLintRequest.
    enable_lint_rules = False


class SqlfluffLintRequest(LintTargetsRequest):
    field_set_type = SqlfluffFieldSet
    tool_subsystem = Sqlfluff
    partitioner_type = PartitionerType.CUSTOM


class SqlfluffFormatRequest(FmtTargetsRequest):
    field_set_type = SqlfluffFieldSet
    tool_subsystem = Sqlfluff
    partitioner_type = PartitionerType.CUSTOM

    @classproperty
    def tool_name(cls) -> str:
        return "sqlfluff format"

    @classproperty
    def tool_id(cls) -> str:
        return "sqlfluff-format"


@dataclass(frozen=True)
class _RunSqlfluffRequest:
    snapshot: Snapshot
    templater: str
    mode: SqlfluffMode


async def run_sqlfluff(
    request: _RunSqlfluffRequest,
    sqlfluff: Sqlfluff,
) -> FallibleProcessResult:
    sqlfluff_pex_get = create_venv_pex(**implicitly({sqlfluff.to_pex_request(): PexRequest}))
    config_files_get = find_config_file(sqlfluff.config_request(request.snapshot.dirs))
    sqlfluff_pex, config_files = await concurrently(sqlfluff_pex_get, config_files_get)
    input_digest = await merge_digests(MergeDigests((request.snapshot.digest, config_files.snapshot.digest)))

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
    templater_args = ["--templater", request.templater]

    result = await execute_process(
        **implicitly(
            VenvPexProcess(
                sqlfluff_pex,
                argv=(*initial_args, *templater_args, *conf_args, *sqlfluff.args, *request.snapshot.files),
                input_digest=input_digest,
                output_files=request.snapshot.files,
                description=f"Run sqlfluff {' '.join(initial_args)} on {pluralize(len(request.snapshot.files), 'file')}.",
                level=LogLevel.DEBUG,
            )
        )
    )
    return result


@dataclass(frozen=True)
class TemplaterMetadata:
    templater: str

    @property
    def description(self) -> str:
        return self.templater


_FS = TypeVar("_FS", bound=FieldSet)


@dataclass(frozen=True)
class GroupByTemplaterRequest(Generic[_FS]):
    field_sets: Sequence[_FS]
    by_file: bool = False


class ConfigParser:
    def __init__(self) -> None:
        self.regex = re.compile("^templater *= *(?P<templater>[^ ]+) *$")

    def parse_templater(self, content: str) -> str | None:
        for line in content.splitlines():
            if match := self.regex.match(line):
                return match.group("templater").strip('"')
        return None


@dataclass(frozen=True)
class NestedConfig:
    templaters: dict[str, str]

    @classmethod
    def new(cls, parser: ConfigParser, contents: Collection[FileContent]) -> NestedConfig:
        templaters = {}
        for file_content in contents:
            content = file_content.content.decode("utf-8")
            templater = parser.parse_templater(content)
            directory = file_content.path.rsplit("/", 1)[0]
            templaters[directory] = templater

        return NestedConfig(templaters)

    def find_templater(self, directory: str) -> str | None:
        for d in recursively(directory):
            templater = self.templaters.get(d)
            if templater is not None:
                return templater
        return None


def recursively(directory: str) -> Iterator[str]:
    while True:
        yield directory
        parts = directory.rsplit("/", 1)
        if len(parts) == 1:
            return

        directory, _ = parts


@rule
async def group_by_templater(request: GroupByTemplaterRequest, sqlfluff: Sqlfluff) -> Partitions:
    dirs = [directory for field_set in request.field_sets for directory in recursively(field_set.address.spec_path)]

    (config_files,) = await concurrently(find_config_file(sqlfluff.config_request(dirs)))
    logger.debug("sqlfluff config files: %s", config_files.snapshot.files)
    contents = await Get(DigestContents, Digest, config_files.snapshot.digest)

    parser = ConfigParser()
    nested_config = NestedConfig.new(parser, contents)
    logger.debug("sqlfluff nested config: %s", nested_config)

    result = defaultdict(list)
    for field_set in request.field_sets:
        directory = field_set.address.spec_path
        templater = nested_config.find_templater(directory)
        if templater is None:
            raise ValueError(f"templater must be defined for {field_set.address}")
        result[templater].append(field_set)

    if request.by_file:
        gets = [
            determine_source_files(SourceFilesRequest(field_set.source for field_set in field_sets))
            for field_sets in result.values()
        ]
        all_source_files = await concurrently(*gets)

        partitions = Partitions(
            Partition(
                elements=source_files.files,
                metadata=TemplaterMetadata(templater),
            )
            for templater, source_files in zip(result, all_source_files)
        )
    else:
        partitions = Partitions(
            Partition(
                elements=tuple(sorted(field_sets, key=lambda fs: fs.address)),
                metadata=TemplaterMetadata(templater),
            )
            for templater, field_sets in result.items()
        )
    logger.debug("sqlfluff partitions: %s", partitions)
    return partitions


@rule(desc="Fix with sqlfluff fix", level=LogLevel.DEBUG)
async def sqlfluff_fix(request: SqlfluffFixRequest.Batch, sqlfluff: Sqlfluff) -> FixResult:
    result = await run_sqlfluff(
        _RunSqlfluffRequest(
            snapshot=request.snapshot,
            templater=request.partition_metadata.templater,
            mode=SqlfluffMode.FIX,
        ),
        sqlfluff,
    )
    return await FixResult.create(request, result)


@rule
async def sqlfluff_fix_partition(request: SqlfluffFixRequest.PartitionRequest) -> Partitions:
    return await Get(Partitions, GroupByTemplaterRequest(field_sets=request.field_sets, by_file=True))


@rule(desc="Lint with sqlfluff lint", level=LogLevel.DEBUG)
async def sqlfluff_lint(request: SqlfluffLintRequest.Batch[SqlfluffFieldSet, Any], sqlfluff: Sqlfluff) -> LintResult:
    source_files = await determine_source_files(SourceFilesRequest(field_set.source for field_set in request.elements))
    result = await run_sqlfluff(
        _RunSqlfluffRequest(
            snapshot=source_files.snapshot,
            templater=request.partition_metadata.templater,
            mode=SqlfluffMode.LINT,
        ),
        sqlfluff,
    )
    return LintResult.create(request, result)


@rule
async def sqlfluff_lint_partition(request: SqlfluffLintRequest.PartitionRequest) -> Partitions:
    return await Get(Partitions, GroupByTemplaterRequest(field_sets=request.field_sets))


@rule(desc="Format with sqlfluff format", level=LogLevel.DEBUG)
async def sqlfluff_fmt(request: SqlfluffFormatRequest.Batch, sqlfluff: Sqlfluff) -> FmtResult:
    result = await run_sqlfluff(
        _RunSqlfluffRequest(
            snapshot=request.snapshot,
            templater=request.partition_metadata.templater,
            mode=SqlfluffMode.FMT,
        ),
        sqlfluff,
    )
    return await FmtResult.create(request, result)


@rule
async def sqlfluff_fmt_partition(request: SqlfluffFormatRequest.PartitionRequest) -> Partitions:
    return await Get(Partitions, GroupByTemplaterRequest(field_sets=request.field_sets, by_file=True))


def rules() -> Iterable[Rule]:
    return (
        *collect_rules(),
        *SqlfluffLintRequest.rules(),
        *SqlfluffFixRequest.rules(),
        *SqlfluffFormatRequest.rules(),
        *pex.rules(),
    )
