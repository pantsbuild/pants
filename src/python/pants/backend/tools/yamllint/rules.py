# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
import logging
from typing import Any

from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.backend.tools.yamllint.subsystem import Yamllint
from pants.backend.tools.yamllint.target_types import YamlSourceField
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.partitions import Partitions
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileEntry, MergeDigests, PathGlobs
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest

logger = logging.getLogger(__name__)


class YamllintRequest(LintFilesRequest):
    tool_subsystem = Yamllint


class PartitionMetadata:
    @property
    def description(self) -> None:
        return None


@rule
async def partition_inputs(
    request: YamllintRequest.PartitionRequest, yamllint: Yamllint
) -> Partitions[Any, PartitionMetadata]:
    if yamllint.skip:
        return Partitions()

    matching_filepaths = FilespecMatcher(includes=["**/*.yml", "**/*.yaml"], excludes=[]).matches(
        request.files
    )
    return Partitions.single_partition(matching_filepaths, metadata=PartitionMetadata())


@rule(desc="Lint using yamllint", level=LogLevel.DEBUG)
async def run_yamllint(request: YamllintRequest.Batch[Any, Any], yamllint: Yamllint) -> LintResult:
    yamllint_bin = await Get(Pex, PexRequest, yamllint.to_pex_request())

    config_files = await Get(ConfigFiles, ConfigFilesRequest, yamllint.config_request())

    snapshot = await Get(Snapshot, PathGlobs(request.elements))

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                snapshot.digest,
                yamllint_bin.digest,
                config_files.snapshot.digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        PexProcess(
            yamllint_bin,
            argv=(
                *(("-c", yamllint.config) if yamllint.config else ()),
                *yamllint.args,
                *snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Run yamllint on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *YamllintRequest.rules()]
