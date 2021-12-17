# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from itertools import chain
import logging
from pants.core.target_types import ResourcesFieldSet, ResourcesGeneratorFieldSet
from pants.core.util_rules.archive import ZipBinary
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import SourcesField
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)

logger = logging.getLogger(__name__)

class JvmResourcesRequest(ClasspathEntryRequest):
    field_sets = (
        ResourcesFieldSet,
        ResourcesGeneratorFieldSet,
    )


@rule(desc="Fetch with coursier")
async def assemble_resources_jar(
    zip: ZipBinary,
    union_membership: UnionMembership,
    request: JvmResourcesRequest,
) -> FallibleClasspathEntry:

    # Request the component's direct dependency classpath, and additionally any prerequisite.
    classpath_entry_requests = [
        *((request.prerequisite,) if request.prerequisite else ()),
        *(
            ClasspathEntryRequest.for_targets(
                union_membership, component=coarsened_dep, resolve=request.resolve
            )
            for coarsened_dep in request.component.dependencies
        ),
    ]
    direct_dependency_classpath_entries = FallibleClasspathEntry.if_all_succeeded(
        await MultiGet(
            Get(FallibleClasspathEntry, ClasspathEntryRequest, cpe)
            for cpe in classpath_entry_requests
        )
    )

    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    source_files = await Get(
        StrippedSourceFiles,
        SourceFilesRequest([tgt.get(SourcesField) for tgt in request.component.members]),
    )

    output_filename = f"{request.component.representative.address.path_safe_spec}.jar"
    output_files = [output_filename]

    resources_jar_input_digest = source_files.snapshot.digest
    resources_jar_result = await Get(
        ProcessResult,
        Process(
            argv=[
                zip.path,
                output_filename,
                *source_files.snapshot.files,
            ],
            description="Build partial JAR containing resources files",
            input_digest=resources_jar_input_digest,
            output_files=output_files,
        ),
    )

    cpe = ClasspathEntry(resources_jar_result.output_digest, output_files, [])

    merged_cpe_digest = await Get(
        Digest,
        MergeDigests(chain((cpe.digest,), (i.digest for i in direct_dependency_classpath_entries))),
    )

    merged_cpe = ClasspathEntry.merge(
        digest=merged_cpe_digest, entries=[cpe, *direct_dependency_classpath_entries]
    )

    return FallibleClasspathEntry(output_filename, CompileResult.SUCCEEDED, merged_cpe, 0)


def rules():
    return [
        *collect_rules(),
        UnionRule(ClasspathEntryRequest, JvmResourcesRequest),
    ]
