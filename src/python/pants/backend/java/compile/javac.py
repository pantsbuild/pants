# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from itertools import chain

from pants.backend.java.dependency_inference.rules import rules as java_dep_inference_rules
from pants.backend.java.subsystems.javac import JavacSubsystem
from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet, JavaSourceField
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.system_binaries import BashBinary, ZipBinary
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Directory, MergeDigests
from pants.engine.intrinsics import (
    create_digest,
    digest_to_snapshot,
    execute_process,
    merge_digests,
)
from pants.engine.process import Process, ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
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
    compile_classpath_entries,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkRequest, JvmProcess, prepare_jdk_environment
from pants.jvm.strip_jar.strip_jar import StripJarRequest, strip_jar
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
    fallibles = await concurrently(
        compile_classpath_entries(ClasspathEntryRequests(optional_prereq_request)),
        compile_classpath_entries(**implicitly(ClasspathDependenciesRequest(request))),
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

    # Then collect the component's sources.
    component_members_with_sources = tuple(
        t for t in request.component.members if t.has_field(SourcesField)
    )
    component_members_and_source_files = zip(
        component_members_with_sources,
        await concurrently(
            determine_source_files(
                SourceFilesRequest(
                    (t.get(SourcesField),),
                    for_sources_types=(JavaSourceField,),
                    enable_codegen=True,
                )
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
        exported_digest = await merge_digests(
            MergeDigests(cpe.digest for cpe in direct_dependency_classpath_entries)
        )
        classpath_entry = ClasspathEntry.merge(exported_digest, direct_dependency_classpath_entries)
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.SUCCEEDED,
            output=classpath_entry,
            exit_code=0,
        )

    dest_dir = "classfiles"
    dest_dir_digest, jdk = await concurrently(
        create_digest(CreateDigest([Directory(dest_dir)])),
        prepare_jdk_environment(**implicitly(JdkRequest.from_target(request.component))),
    )
    merged_digest = await merge_digests(
        MergeDigests(
            (
                dest_dir_digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_java_source_files
                ),
            )
        )
    )

    usercp = "__cp"
    user_classpath = Classpath(direct_dependency_classpath_entries, request.resolve)
    classpath_arg = ":".join(user_classpath.immutable_inputs_args(prefix=usercp))
    immutable_input_digests = dict(user_classpath.immutable_inputs(prefix=usercp))

    # Compile.
    compile_result = await execute_process(
        **implicitly(
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
            )
        )
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
    output_snapshot = await digest_to_snapshot(compile_result.output_digest)
    output_file = compute_output_jar_filename(request.component)
    output_files: tuple[str, ...] = (output_file,)
    if output_snapshot.files:
        jar_result = await execute_process_or_raise(
            **implicitly(
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
                    cache_scope=ProcessCacheScope.LOCAL_SUCCESSFUL,
                )
            )
        )
        jar_output_digest = jar_result.output_digest
    else:
        # If there was no output, then do not create a jar file. This may occur, for example, when compiling
        # a `package-info.java` in a single partition.
        output_files = ()
        jar_output_digest = EMPTY_DIGEST

    if jvm.reproducible_jars:
        jar_output_digest = await strip_jar(
            **implicitly(StripJarRequest(digest=jar_output_digest, filenames=output_files))
        )
    output_classpath = ClasspathEntry(
        jar_output_digest, output_files, direct_dependency_classpath_entries
    )

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
