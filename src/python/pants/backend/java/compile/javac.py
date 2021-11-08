# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from itertools import chain

from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet, JavaSourceField
from pants.core.util_rules.archive import ZipBinary
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    Snapshot,
)
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesField
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkSetup
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CompileJavaSourceRequest(ClasspathEntryRequest):
    field_sets = (JavaFieldSet, JavaGeneratorFieldSet)


@rule(desc="Compile with javac")
async def compile_java_source(
    bash: BashBinary,
    jdk_setup: JdkSetup,
    zip_binary: ZipBinary,
    union_membership: UnionMembership,
    request: CompileJavaSourceRequest,
) -> FallibleClasspathEntry:
    # Request the component's direct dependency classpath.
    direct_dependency_classpath_entries = FallibleClasspathEntry.if_all_succeeded(
        await MultiGet(
            Get(
                FallibleClasspathEntry,
                ClasspathEntryRequest,
                ClasspathEntryRequest.for_targets(
                    union_membership, component=coarsened_dep, resolve=request.resolve
                ),
            )
            for coarsened_dep in request.component.dependencies
        )
    )
    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    # Then collect the component's sources.
    component_members_with_sources = tuple(
        t for t in request.component.members if t.has_field(SourcesField)
    )
    component_members_and_source_files = zip(
        component_members_with_sources,
        await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest(
                    (t.get(SourcesField),),
                    for_sources_types=(JavaSourceField,),
                    enable_codegen=True,
                ),
            )
            for t in component_members_with_sources
        ),
    )
    component_members_and_java_source_files = [
        (target, sources)
        for target, sources in component_members_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]
    if not component_members_and_java_source_files:
        # Is a generator, and so exports all of its direct deps.
        exported_digest = await Get(
            Digest, MergeDigests(cpe.digest for cpe in direct_dependency_classpath_entries)
        )
        classpath_entry = ClasspathEntry.merge(exported_digest, direct_dependency_classpath_entries)
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.SUCCEEDED,
            output=classpath_entry,
            exit_code=0,
        )

    dest_dir = "classfiles"
    (merged_direct_dependency_classpath_digest, dest_dir_digest) = await MultiGet(
        Get(
            Digest,
            MergeDigests(classfiles.digest for classfiles in direct_dependency_classpath_entries),
        ),
        Get(
            Digest,
            CreateDigest([Directory(dest_dir)]),
        ),
    )

    usercp = "__cp"
    prefixed_direct_dependency_classpath_digest = await Get(
        Digest, AddPrefix(merged_direct_dependency_classpath_digest, usercp)
    )
    classpath_arg = ClasspathEntry.arg(direct_dependency_classpath_entries, prefix=usercp)

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_direct_dependency_classpath_digest,
                dest_dir_digest,
                jdk_setup.digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_java_source_files
                ),
            )
        ),
    )

    # Compile.
    compile_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, [f"{jdk_setup.java_home}/lib/tools.jar"]),
                "com.sun.tools.javac.Main",
                *(("-cp", classpath_arg) if classpath_arg else ()),
                "-d",
                dest_dir,
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_java_source_files
                    )
                ),
            ],
            input_digest=merged_digest,
            use_nailgun=jdk_setup.digest,
            append_only_caches=jdk_setup.append_only_caches,
            env=jdk_setup.env,
            output_directories=(dest_dir,),
            description=f"Compile {request.component} with javac",
            level=LogLevel.DEBUG,
        ),
    )
    if compile_result.exit_code != 0:
        return FallibleClasspathEntry.from_fallible_process_result(
            str(request.component),
            compile_result,
            None,
        )

    # Jar.
    # NB: We jar up the outputs in a separate process because the nailgun runner cannot support
    # invoking via a `bash` wrapper (since the trailing portion of the command is executed by
    # the nailgun server). We might be able to resolve this in the future via a Javac wrapper shim.
    output_snapshot = await Get(Snapshot, Digest, compile_result.output_digest)
    output_file = f"{request.component.representative.address.path_safe_spec}.jar"
    if output_snapshot.files:
        jar_result = await Get(
            ProcessResult,
            Process(
                argv=[
                    bash.path,
                    "-c",
                    " ".join(
                        ["cd", dest_dir, ";", zip_binary.path, "-r", f"../{output_file}", "."]
                    ),
                ],
                input_digest=compile_result.output_digest,
                output_files=(output_file,),
                description=f"Capture outputs of {request.component} for javac",
                level=LogLevel.TRACE,
            ),
        )
        jar_output_digest = jar_result.output_digest
    else:
        # If there was no output, then do not create a jar file. This may occur, for example, when compiling
        # a `package-info.java` in a single partition.
        jar_output_digest = EMPTY_DIGEST

    return FallibleClasspathEntry.from_fallible_process_result(
        str(request.component),
        compile_result,
        ClasspathEntry(jar_output_digest, (output_file,), direct_dependency_classpath_entries),
    )


def rules():
    return [
        *collect_rules(),
        *jvm_compile_rules(),
        UnionRule(ClasspathEntryRequest, CompileJavaSourceRequest),
    ]
