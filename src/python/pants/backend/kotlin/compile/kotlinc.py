# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging

from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet
from pants.backend.kotlin.compile.kotlinc_plugins import (
    KotlincPlugins,
    KotlincPluginsForTargetRequest,
    KotlincPluginsRequest,
    KotlincPluginTargetsForTarget,
)
from pants.backend.kotlin.subsystems.kotlin import KotlinSubsystem
from pants.backend.kotlin.subsystems.kotlinc import KotlincSubsystem
from pants.backend.kotlin.target_types import (
    KotlinFieldSet,
    KotlinGeneratorFieldSet,
    KotlinSourceField,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTarget, SourcesField
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntries,
    FallibleClasspathEntry,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CompileKotlinSourceRequest(ClasspathEntryRequest):
    field_sets = (KotlinFieldSet, KotlinGeneratorFieldSet)
    field_sets_consume_only = (JavaFieldSet, JavaGeneratorFieldSet)


def compute_output_jar_filename(ctgt: CoarsenedTarget) -> str:
    return f"{ctgt.representative.address.path_safe_spec}.kotlin.jar"


@rule(desc="Compile with kotlinc")
async def compile_kotlin_source(
    kotlin: KotlinSubsystem,
    kotlinc: KotlincSubsystem,
    request: CompileKotlinSourceRequest,
) -> FallibleClasspathEntry:
    # Request classpath entries for our direct dependencies.
    dependency_cpers = await Get(FallibleClasspathEntries, ClasspathDependenciesRequest(request))
    direct_dependency_classpath_entries = dependency_cpers.if_all_succeeded()

    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    kotlin_version = kotlin.version_for_resolve(request.resolve.name)

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
                    for_sources_types=(KotlinSourceField,),
                    enable_codegen=True,
                ),
            )
            for t in component_members_with_sources
        ),
    )

    plugins_ = await MultiGet(
        Get(
            KotlincPluginTargetsForTarget,
            KotlincPluginsForTargetRequest(target, request.resolve.name),
        )
        for target in request.component.members
    )
    plugins_request = KotlincPluginsRequest.from_target_plugins(plugins_, request.resolve)
    local_plugins = await Get(KotlincPlugins, KotlincPluginsRequest, plugins_request)

    component_members_and_kotlin_source_files = [
        (target, sources)
        for target, sources in component_members_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]

    if not component_members_and_kotlin_source_files:
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

    toolcp_relpath = "__toolcp"
    local_kotlinc_plugins_relpath = "__localplugincp"
    usercp = "__cp"

    user_classpath = Classpath(direct_dependency_classpath_entries, request.resolve)

    tool_classpath, sources_digest, jdk = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-compiler-embeddable",
                            version=kotlin_version,
                        ),
                        Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-scripting-compiler-embeddable",
                            version=kotlin_version,
                        ),
                    ]
                ),
            ),
        ),
        Get(
            Digest,
            MergeDigests(
                (
                    sources.snapshot.digest
                    for _, sources in component_members_and_kotlin_source_files
                )
            ),
        ),
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_target(request.component)),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        local_kotlinc_plugins_relpath: local_plugins.classpath.digest,
    }
    extra_nailgun_keys = tuple(extra_immutable_input_digests)
    extra_immutable_input_digests.update(user_classpath.immutable_inputs(prefix=usercp))

    classpath_arg = ":".join(user_classpath.immutable_inputs_args(prefix=usercp))

    output_file = compute_output_jar_filename(request.component)
    process_result = await Get(
        FallibleProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
            argv=[
                "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                *(("-classpath", classpath_arg) if classpath_arg else ()),
                "-d",
                output_file,
                *(local_plugins.args(local_kotlinc_plugins_relpath)),
                *kotlinc.args,
                *sorted(
                    itertools.chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_kotlin_source_files
                    )
                ),
            ],
            input_digest=sources_digest,
            extra_immutable_input_digests=extra_immutable_input_digests,
            extra_nailgun_keys=extra_nailgun_keys,
            output_files=(output_file,),
            description=f"Compile {request.component} with kotlinc",
            level=LogLevel.DEBUG,
        ),
    )
    output: ClasspathEntry | None = None
    if process_result.exit_code == 0:
        output = ClasspathEntry(
            process_result.output_digest, (output_file,), direct_dependency_classpath_entries
        )

    return FallibleClasspathEntry.from_fallible_process_result(
        str(request.component),
        process_result,
        output,
    )


def rules():
    return (
        *collect_rules(),
        *jvm_compile_rules(),
        UnionRule(ClasspathEntryRequest, CompileKotlinSourceRequest),
    )
