# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# This file should be moved once we figure out where everything belongs

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Union

from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Rule, collect_rules, rule, rule_helper
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    GeneratedSources,
    GenerateSourcesRequest,
    MultipleSourcesField,
    SourcesField,
    SpecialCasedDependencies,
    StringSequenceField,
    Target,
    Targets,
)
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReexportRuleAndTarget:
    rules: tuple[Union[Rule, UnionRule], ...]
    target_types: tuple[type[Target], ...]


class ActivateReexportTargetFieldBase(MultipleSourcesField):
    # We solely register so that codegen can match a fieldset.
    # One unique subclass must be defined per target type.
    alias = "_sources"
    uses_source_roots = False
    expected_num_files = 0


class ReExportInputsField(SpecialCasedDependencies):
    alias = "inputs"
    required = True


class ReExportOutputsField(StringSequenceField):
    alias = "outputs"
    required = False


@rule_helper
async def _reexport(wrapper: GenerateSourcesRequest) -> GeneratedSources:
    request = wrapper.protocol_target
    default_extensions = {i for i in (wrapper.output.expected_file_extensions or ()) if i}

    inputs = await Get(
        Targets,
        UnparsedAddressInputs,
        request.get(ReExportInputsField).to_unparsed_address_inputs(),
    )

    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[tgt.get(SourcesField) for tgt in inputs],
            for_sources_types=(SourcesField, FileSourceField),
            enable_codegen=True,
        ),
    )

    outputs_value: Iterable[str] | None = request.get(ReExportOutputsField).value
    if not outputs_value:
        outputs_value = [i for i in sources.files if any(i.endswith(j) for j in default_extensions)]

    # I'm sure there's a better way to do this, but this works for now.
    filter_digest = await Get(
        ProcessResult,
        Process(
            argv=("/usr/bin/true",),
            description="Filter digest",
            input_digest=sources.snapshot.digest,
            output_files=outputs_value,
        ),
    )

    snapshot = await Get(Snapshot, Digest, filter_digest.output_digest)
    return GeneratedSources(snapshot)


def reexport_rule_and_target(
    source_field_type: type[SourcesField], target_name: str
) -> ReexportRuleAndTarget:
    class ActivateReexportTargetField(ActivateReexportTargetFieldBase):
        pass

    class GenerateReexportedSourcesRequest(GenerateSourcesRequest):
        input = ActivateReexportTargetField
        output = source_field_type

    class ExportTarget(Target):
        alias = target_name
        core_fields = (
            *COMMON_TARGET_FIELDS,
            ActivateReexportTargetField,
            ReExportInputsField,
            ReExportOutputsField,
        )

    # need to use `_param_type_overrides` to stop `@rule` from inspecting the source
    @rule(_param_type_overrides={"request": GenerateReexportedSourcesRequest})
    async def reexport(request: GenerateSourcesRequest) -> GeneratedSources:
        return await _reexport(request)

    return ReexportRuleAndTarget(
        rules=(
            *collect_rules(locals()),
            UnionRule(GenerateSourcesRequest, GenerateReexportedSourcesRequest),
        ),
        target_types=(ExportTarget,),
    )
