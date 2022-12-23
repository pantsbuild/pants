# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# This file should be moved once we figure out where everything belongs

from __future__ import annotations

import logging
from typing import Iterable

from pants.backend.python.target_types import PythonSourceField
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
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


class ActivateExportPythonTargetSourcesField(MultipleSourcesField):
    # We solely register so that codegen can match a fieldset. One must be defined per target type.
    alias = "_sources"
    uses_source_roots = False
    expected_num_files = 0


class GenerateExportedPythonSourcesRequest(GenerateSourcesRequest):
    input = ActivateExportPythonTargetSourcesField
    output = PythonSourceField


class ReExportInputsField(SpecialCasedDependencies):
    alias = "inputs"
    required = True


class ReExportOutputsField(StringSequenceField):
    alias = "outputs"
    required = False


class ExperimentalExportPython(Target):
    alias = "experimental_export_python"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ActivateExportPythonTargetSourcesField,
        ReExportInputsField,
        ReExportOutputsField,
    )


@rule
async def magic(wrapper: GenerateExportedPythonSourcesRequest) -> GeneratedSources:
    request = wrapper.protocol_target
    default_extensions = {i for i in wrapper.output.expected_file_extensions if i}

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


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateExportedPythonSourcesRequest),
    ]


def targets():
    return [
        ExperimentalExportPython,
    ]
