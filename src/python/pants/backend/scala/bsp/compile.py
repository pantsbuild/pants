# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""BSP-specific Scala compile rule.

Mirrors `pants.backend.scala.compile.scalac.compile_scala_source` with one
substantive difference: source files are passed to scalac at their original
workspace-relative paths (via `determine_source_files`) rather than with
source roots stripped (via `strip_source_roots`).

This matters for the SemanticDB plugin, which uses the input source path to
name its `META-INF/semanticdb/<source>.semanticdb` outputs. Metals (and other
BSP clients) look up SemanticDB by workspace-relative path; stripping source
roots causes a lookup mismatch and "empty definition using pc, found symbol
in pc: <none>" reports. With unstripped paths and the standard
`-P:semanticdb:sourceroot:.` scalac option, the SemanticDB output is
workspace-relative both in the filename and in the internal `uri` field.

The non-BSP `compile_scala_source` is unchanged: it intentionally strips
source roots so that scalac compilations consumed by tools that expect
source-root-relative naming (e.g. scalafix CLI) continue to work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.java.target_types import JavaSourceField
from pants.backend.scala.compile.scalac import compute_output_jar_filename
from pants.backend.scala.compile.scalac_plugins import (
    ScalaPluginsForTargetRequest,
    ScalaPluginsRequest,
    fetch_plugins,
    resolve_scala_plugins_for_target,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaSourceField
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    resolve_scala_artifacts_for_version,
)
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.system_binaries import BashBinary, ZipBinary
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Directory, MergeDigests
from pants.engine.internals.native_engine import Digest
from pants.engine.intrinsics import create_digest, execute_process, merge_digests
from pants.engine.process import Process, ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import CoarsenedTarget, SourcesField
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
    compile_classpath_entries,
)
from pants.jvm.jdk_rules import JdkRequest, JvmProcess, prepare_jdk_environment
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import ToolClasspathRequest, materialize_classpath_for_tool
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.strip_jar.strip_jar import StripJarRequest
from pants.jvm.strip_jar.strip_jar import strip_jar as strip_jar_get
from pants.jvm.subsystems import JvmSubsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompileScalaSourceBSPRequest(ClasspathEntryRequest):
    """BSP variant of `CompileScalaSourceRequest`.

    Subclasses `ClasspathEntryRequest` so that the existing
    `ClasspathDependenciesRequest` plumbing can consume it (it accesses
    `.component` and `.resolve`), but is deliberately NOT registered as a
    `UnionRule(ClasspathEntryRequest, …)` member — that would clash with
    `CompileScalaSourceRequest` in the union dispatch. The BSP code path
    calls `compile_scala_source_bsp` directly.
    """

    # `field_sets`/`field_sets_consume_only` are inherited as `ClassVar` from the
    # base class but never read by the dispatcher because we don't register
    # this class. They're carried for completeness.


@rule(desc="Compile with scalac (BSP)")
async def compile_scala_source_bsp(
    scala: ScalaSubsystem,
    jvm: JvmSubsystem,
    scalac: Scalac,
    bash: BashBinary,
    zip_binary: ZipBinary,
    request: CompileScalaSourceBSPRequest,
) -> FallibleClasspathEntry:
    # Request classpath entries for our direct dependencies.
    dependency_cpers = await compile_classpath_entries(
        **implicitly(ClasspathDependenciesRequest(request))
    )
    direct_dependency_classpath_entries = dependency_cpers.if_all_succeeded()

    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    scala_version = scala.version_for_resolve(request.resolve.name)
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(scala_version)
    )

    component_members_with_sources = tuple(
        t for t in request.component.members if t.has_field(SourcesField)
    )
    component_members_and_source_files = zip(
        component_members_with_sources,
        await concurrently(
            # Key BSP-specific difference vs. `compile_scala_source`: pass
            # un-stripped source paths to scalac so the SemanticDB plugin
            # emits workspace-relative paths (filename + internal `uri`
            # payload). Metals looks up SemanticDB by workspace-relative
            # path; stripped paths cause `empty definition using pc`.
            determine_source_files(
                SourceFilesRequest(
                    (t.get(SourcesField),),
                    for_sources_types=(ScalaSourceField, JavaSourceField),
                    enable_codegen=True,
                )
            )
            for t in component_members_with_sources
        ),
    )

    plugins_ = await concurrently(
        resolve_scala_plugins_for_target(
            ScalaPluginsForTargetRequest(target, request.resolve.name), **implicitly()
        )
        for target in request.component.members
    )
    plugins_request = ScalaPluginsRequest.from_target_plugins(plugins_, request.resolve)
    local_plugins = await fetch_plugins(plugins_request)

    component_members_and_scala_source_files = [
        (target, sources)
        for target, sources in component_members_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]

    if not component_members_and_scala_source_files:
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

    toolcp_relpath = "__toolcp"
    local_scalac_plugins_relpath = "__localplugincp"
    usercp = "__cp"

    user_classpath = Classpath(direct_dependency_classpath_entries, request.resolve)

    tool_classpath, sources_digest, jdk = await concurrently(
        materialize_classpath_for_tool(
            ToolClasspathRequest(
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        scala_artifacts.compiler_coordinate,
                        scala_artifacts.library_coordinate,
                    ]
                ),
            )
        ),
        merge_digests(
            MergeDigests(
                (sources.snapshot.digest for _, sources in component_members_and_scala_source_files)
            )
        ),
        prepare_jdk_environment(**implicitly(JdkRequest.from_target(request.component))),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        local_scalac_plugins_relpath: local_plugins.classpath.digest,
    }
    extra_nailgun_keys = tuple(extra_immutable_input_digests)
    extra_immutable_input_digests.update(user_classpath.immutable_inputs(prefix=usercp))

    classpath_arg = ":".join(user_classpath.immutable_inputs_args(prefix=usercp))

    output_file = compute_output_jar_filename(request.component)
    compilation_output_dir = "__out"
    compilation_empty_dir = await create_digest(CreateDigest([Directory(compilation_output_dir)]))
    merged_digest: Digest = await merge_digests(
        MergeDigests([sources_digest, compilation_empty_dir])
    )
    compile_result = await execute_process(
        **implicitly(
            JvmProcess(
                jdk=jdk,
                classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
                argv=[
                    scala_artifacts.compiler_main,
                    "-bootclasspath",
                    ":".join(tool_classpath.classpath_entries(toolcp_relpath)),
                    *local_plugins.args(local_scalac_plugins_relpath),
                    *(("-classpath", classpath_arg) if classpath_arg else ()),
                    *scalac.parsed_args_for_resolve(request.resolve.name),
                    "-d",
                    compilation_output_dir,
                    *sorted(
                        chain.from_iterable(
                            sources.snapshot.files
                            for _, sources in component_members_and_scala_source_files
                        )
                    ),
                ],
                input_digest=merged_digest,
                extra_immutable_input_digests=extra_immutable_input_digests,
                extra_nailgun_keys=extra_nailgun_keys,
                output_directories=(compilation_output_dir,),
                description=f"Compile {request.component} with scalac (BSP)",
                level=LogLevel.DEBUG,
            )
        )
    )
    output: ClasspathEntry | None = None
    if compile_result.exit_code == 0:
        # We package the outputs into a JAR file in a similar way as how it's
        # done in the `javac.py` implementation
        jar_result = await execute_process_or_raise(
            **implicitly(
                Process(
                    argv=[
                        bash.path,
                        "-c",
                        " ".join(
                            [
                                "cd",
                                compilation_output_dir,
                                ";",
                                zip_binary.path,
                                "-r",
                                f"../{output_file}",
                                ".",
                            ]
                        ),
                    ],
                    input_digest=compile_result.output_digest,
                    output_files=(output_file,),
                    description=f"Capture outputs of {request.component} for scalac (BSP)",
                    level=LogLevel.TRACE,
                    cache_scope=ProcessCacheScope.LOCAL_SUCCESSFUL,
                )
            )
        )
        output_digest = jar_result.output_digest

        if jvm.reproducible_jars:
            output_digest = await strip_jar_get(
                **implicitly(StripJarRequest(digest=output_digest, filenames=(output_file,)))
            )

        output = ClasspathEntry(output_digest, (output_file,), direct_dependency_classpath_entries)

    return FallibleClasspathEntry.from_fallible_process_result(
        str(request.component),
        compile_result,
        output,
    )


def rules():
    return collect_rules()
