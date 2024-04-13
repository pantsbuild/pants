# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from itertools import chain

from pants.backend.java.dependency_inference.rules import (
    JavaInferredDependencies,
    JavaInferredDependenciesAndExportsRequest,
)
from pants.backend.java.dependency_inference.rules import rules as java_dep_inference_rules
from pants.backend.java.subsystems.javac import JavacSubsystem
from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet, JavaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import BashBinary, ZipBinary
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, Directory, MergeDigests, Snapshot
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, SourcesField
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    ClasspathEntryRequests,
    CompileResult,
    FallibleClasspathEntries,
    FallibleClasspathEntry,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.strip_jar.strip_jar import StripJarRequest
from pants.jvm.subsystems import JvmSubsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CompileJavaSourceRequest(ClasspathEntryRequest):
    field_sets = (JavaFieldSet, JavaGeneratorFieldSet)


# TODO: This code is duplicated in the javac and BSP rules.
def compute_output_jar_filename(ctgt: CoarsenedTarget) -> str:
    return f"{ctgt.representative.address.path_safe_spec}.javac.jar"


@rule(desc="Compile with javac")
async def compile_java_source(
    bash: BashBinary,
    javac: JavacSubsystem,
    zip_binary: ZipBinary,
    jvm: JvmSubsystem,
    request: CompileJavaSourceRequest,
) -> FallibleClasspathEntry:
    # Request the component's direct dependency classpath, and additionally any prerequisite.
    optional_prereq_request = [*((request.prerequisite,) if request.prerequisite else ())]
    fallibles = await MultiGet(
        Get(FallibleClasspathEntries, ClasspathEntryRequests(optional_prereq_request)),
        Get(FallibleClasspathEntries, ClasspathDependenciesRequest(request)),
    )

    direct_dependency_classpath_entries = FallibleClasspathEntries(
        itertools.chain(*fallibles)
    ).if_all_succeeded()

    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    # Capture just the `ClasspathEntry` objects that are listed as `export` types by source analysis
    deps_to_classpath_entries = dict(
        zip(request.component.dependencies, direct_dependency_classpath_entries or ())
    )
    # Re-request inferred dependencies to get a list of export dependency addresses
    inferred_dependencies = await MultiGet(
        Get(
            JavaInferredDependencies,
            JavaInferredDependenciesAndExportsRequest(tgt[JavaSourceField]),
        )
        for tgt in request.component.members
        if JavaFieldSet.is_applicable(tgt)
    )
    flat_exports = {export for i in inferred_dependencies for export in i.exports}

    export_classpath_entries = [
        classpath_entry
        for coarsened_target, classpath_entry in deps_to_classpath_entries.items()
        if any(m.address in flat_exports for m in coarsened_target.members)
    ]

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
    dest_dir_digest, jdk = await MultiGet(
        Get(
            Digest,
            CreateDigest([Directory(dest_dir)]),
        ),
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_target(request.component)),
    )
    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                dest_dir_digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_java_source_files
                ),
            )
        ),
    )

    usercp = "__cp"
    user_classpath = Classpath(direct_dependency_classpath_entries, request.resolve)
    classpath_arg = ":".join(user_classpath.root_immutable_inputs_args(prefix=usercp))
    immutable_input_digests = dict(user_classpath.root_immutable_inputs(prefix=usercp))

    # Compile.
    compile_result = await Get(
        FallibleProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{jdk.java_home}/lib/tools.jar"],
            argv=[
                "com.sun.tools.javac.Main",
                *(("-cp", classpath_arg) if classpath_arg else ()),
                *javac.args,
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
            extra_immutable_input_digests=immutable_input_digests,
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
    output_file = compute_output_jar_filename(request.component)
    output_files: tuple[str, ...] = (output_file,)
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
                output_files=output_files,
                description=f"Capture outputs of {request.component} for javac",
                level=LogLevel.TRACE,
            ),
        )
        jar_output_digest = jar_result.output_digest
    else:
        # If there was no output, then do not create a jar file. This may occur, for example, when compiling
        # a `package-info.java` in a single partition.
        output_files = ()
        jar_output_digest = EMPTY_DIGEST

    if jvm.reproducible_jars:
        jar_output_digest = await Get(
            Digest, StripJarRequest(digest=jar_output_digest, filenames=output_files)
        )
    output_classpath = ClasspathEntry(
        jar_output_digest, output_files, direct_dependency_classpath_entries
    )

    if export_classpath_entries:
        merged_export_digest = await Get(
            Digest,
            MergeDigests((output_classpath.digest, *(i.digest for i in export_classpath_entries))),
        )
        merged_classpath = ClasspathEntry.merge(
            merged_export_digest, (output_classpath, *export_classpath_entries)
        )
        output_classpath = merged_classpath

    return FallibleClasspathEntry.from_fallible_process_result(
        str(request.component),
        compile_result,
        output_classpath,
    )


def rules():
    return [
        *collect_rules(),
        *java_dep_inference_rules(),
        *jvm_compile_rules(),
        UnionRule(ClasspathEntryRequest, CompileJavaSourceRequest),
    ]
