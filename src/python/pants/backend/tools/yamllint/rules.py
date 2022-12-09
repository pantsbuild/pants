# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any

from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.backend.tools.yamllint.subsystem import Yamllint
from pants.backend.tools.yamllint.target_types import YamlSourceField
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class YamllintFieldSet(FieldSet):
    required_fields = (YamlSourceField,)
    sources: YamlSourceField


class YamllintRequest(LintTargetsRequest):
    field_set_type = YamllintFieldSet
    tool_subsystem = Yamllint
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Lint using yamllint", level=LogLevel.DEBUG)
async def run_yamllint(
    request: YamllintRequest.Batch[YamllintFieldSet, Any], yamllint: Yamllint
) -> LintResult:
    sources_get = Get(
        SourceFiles,
        SourceFilesRequest(
            (field_set.sources for field_set in request.elements),
            for_sources_types=(YamlSourceField,),
        ),
    )
    yamllint_bin_get = Get(Pex, PexRequest, yamllint.to_pex_request())

    sources, yamllint_bin = await MultiGet(sources_get, yamllint_bin_get)

    config_files = await Get(ConfigFiles, ConfigFilesRequest, yamllint.config_request())

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                sources.snapshot.digest,
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
                *sources.snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Run yamllint on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *YamllintRequest.rules()]
