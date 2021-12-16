# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.archive import ZipBinary
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import SourcesField
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)
from pants.jvm.target_types import JvmResourcesFieldSet, JvmResourcesGeneratorFieldSet


class JvmResourcesRequest(ClasspathEntryRequest):
    field_sets = (
        JvmResourcesFieldSet,
        JvmResourcesGeneratorFieldSet,
    )


_PANTS_RESOURCES_PARTIAL_JAR_FILENAME = "pants-resources.jar"


@rule(desc="Fetch with coursier")
async def assemble_resources_jar(
    bash: BashBinary,
    zip: ZipBinary,
    request: JvmResourcesRequest,
) -> FallibleClasspathEntry:

    source_files = await Get(
        StrippedSourceFiles,
        SourceFilesRequest([tgt.get(SourcesField) for tgt in request.component.members]),
    )

    resources_jar_input_digest = source_files.snapshot.digest
    resources_jar_result = await Get(
        ProcessResult,
        Process(
            argv=[
                zip.path,
                _PANTS_RESOURCES_PARTIAL_JAR_FILENAME,
                *source_files.snapshot.files,
            ],
            description="Build partial JAR containing resources files file",
            input_digest=resources_jar_input_digest,
            output_files=[_PANTS_RESOURCES_PARTIAL_JAR_FILENAME],
        ),
    )

    cpe = ClasspathEntry(
        resources_jar_result.output_digest, [_PANTS_RESOURCES_PARTIAL_JAR_FILENAME], []
    )
    return FallibleClasspathEntry("Resources JAR assembly", CompileResult.SUCCEEDED, cpe, 0)


def rules():
    return [
        *collect_rules(),
        UnionRule(ClasspathEntryRequest, JvmResourcesRequest),
    ]
