# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.soap.java import dependency_inference, extra_fields, symbol_mapper
from pants.backend.codegen.soap.java.extra_fields import JavaModuleField, JavaPackageField
from pants.backend.codegen.soap.java.jaxws import JaxWsTools
from pants.backend.codegen.soap.target_types import (
    WsdlSourceField,
    WsdlSourcesGeneratorTarget,
    WsdlSourceTarget,
)
from pants.backend.java.target_types import JavaSourceField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.goals.resolves import ExportableTool
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm import jdk_rules
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateJavaFromWsdlRequest(GenerateSourcesRequest):
    input = WsdlSourceField
    output = JavaSourceField


@dataclass(frozen=True)
class CompileWsdlSourceRequest:
    digest: Digest
    path: str
    module: str | None = None
    package: str | None = None


@dataclass(frozen=True)
class CompiledWsdlSource:
    output_digest: Digest


@rule(desc="Generate Java sources from WSDL", level=LogLevel.DEBUG)
async def generate_java_from_wsdl(request: GenerateJavaFromWsdlRequest) -> GeneratedSources:
    sources = await Get(
        HydratedSources, HydrateSourcesRequest(request.protocol_target[WsdlSourceField])
    )

    target_package = request.protocol_target[JavaPackageField].value
    compile_results = await MultiGet(
        Get(
            CompiledWsdlSource,
            CompileWsdlSourceRequest(
                sources.snapshot.digest,
                path=path,
                module=request.protocol_target[JavaModuleField].value,
                package=target_package,
            ),
        )
        for path in sources.snapshot.files
    )

    merged_output_digests, source_root = await MultiGet(
        Get(Digest, MergeDigests([r.output_digest for r in compile_results])),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(merged_output_digests, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, merged_output_digests)
    )
    return GeneratedSources(source_root_restored)


@rule(level=LogLevel.DEBUG)
async def compile_wsdl_source(
    request: CompileWsdlSourceRequest,
    jdk: InternalJdk,
    jaxws: JaxWsTools,
) -> CompiledWsdlSource:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"

    lockfile_request = GenerateJvmLockfileFromTool.create(jaxws)
    tool_classpath, subsetted_input_digest, empty_output_dir = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(lockfile=lockfile_request),
        ),
        Get(
            Digest,
            DigestSubset(
                request.digest,
                PathGlobs(
                    [request.path],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    conjunction=GlobExpansionConjunction.all_match,
                    description_of_origin="the WSDL file name",
                ),
            ),
        ),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )

    input_digest = await Get(Digest, MergeDigests([subsetted_input_digest, empty_output_dir]))

    immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    jaxws_args = [
        "-d",
        output_dir,
        "-encoding",
        "utf8",
        "-keep",
        "-Xnocompile",
        "-B-XautoNameResolution",
    ]
    if request.module:
        jaxws_args.extend(["-m", request.module])
    if request.package:
        jaxws_args.extend(["-p", request.package])

    jaxws_process = JvmProcess(
        jdk=jdk,
        argv=[
            "com.sun.tools.ws.WsImport",
            *jaxws_args,
            request.path,
        ],
        classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
        input_digest=input_digest,
        extra_jvm_options=jaxws.jvm_options,
        extra_immutable_input_digests=immutable_input_digests,
        extra_nailgun_keys=immutable_input_digests,
        description="Generating Java sources from WSDL source",
        level=LogLevel.DEBUG,
        output_directories=(output_dir,),
    )
    jaxws_result = await Get(ProcessResult, JvmProcess, jaxws_process)

    normalized_digest = await Get(Digest, RemovePrefix(jaxws_result.output_digest, output_dir))
    return CompiledWsdlSource(normalized_digest)


def rules():
    return [
        *collect_rules(),
        *extra_fields.rules(),
        *dependency_inference.rules(),
        *symbol_mapper.rules(),
        *jvm_tool.rules(),
        *jdk_rules.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromWsdlRequest),
        UnionRule(ExportableTool, JaxWsTools),
        WsdlSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        WsdlSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        WsdlSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        WsdlSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
    ]
