# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pants.backend.java.subsystems.jmh import Jmh
from pants.core.goals.bench import (
    BenchmarkExtraEnv,
    BenchmarkFieldSet,
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkSubsystem,
)
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address, Addresses
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesField, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.jvm.target_types import (
    JmhBenchmarkExtraEnvVarsField,
    JmhBenchmarkSourceField,
    JmhBenchmarkTimeoutField,
    JvmDependenciesField,
    JvmJdkField,
)
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class JmhBenchmarkFieldSet(BenchmarkFieldSet):
    required_fields = (JmhBenchmarkSourceField, JvmJdkField)

    sources: JmhBenchmarkSourceField
    timeout: JmhBenchmarkTimeoutField
    jdk_version: JvmJdkField
    dependencies: JvmDependenciesField
    extra_env_vars: JmhBenchmarkExtraEnvVarsField


class JmhBenchmarkRequest(BenchmarkRequest):
    tool_subsystem = Jmh
    field_set_type = JmhBenchmarkFieldSet


class JmhToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = Jmh.options_scope


@dataclass(frozen=True)
class JmhSetupRequest:
    field_set: JmhBenchmarkFieldSet


@dataclass(frozen=True)
class JmhSetup:
    process: JvmProcess
    reports_dir_prefix: str


@dataclass(frozen=True)
class GeneratedJmhSources:
    digest: Digest


@dataclass(frozen=True)
class GenerateJmhSourcesRequest:
    address: Address
    jdk: JdkEnvironment
    jmh_classpath: ToolClasspath
    classpath: Classpath
    extra_files: Digest


@rule(level=LogLevel.DEBUG)
async def setup_jmh_for_target(
    request: JmhSetupRequest,
    jmh: Jmh,
    bench_subsystem: BenchmarkSubsystem,
    bench_extra_env: BenchmarkExtraEnv,
) -> JmhSetup:
    jdk, transitive_tgts = await MultiGet(
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(request.field_set.jdk_version)),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.field_set.address])),
    )

    lockfile_request = await Get(GenerateJvmLockfileFromTool, JmhToolLockfileSentinel())
    classpath, jmh_classpath, files = await MultiGet(
        Get(Classpath, Addresses([request.field_set.address])),
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(
            SourceFiles,
            SourceFilesRequest(
                (dep.get(SourcesField) for dep in transitive_tgts.dependencies),
                for_sources_types=(FileSourceField,),
                enable_codegen=True,
            ),
        ),
    )

    # jmh_generated = await Get(
    #     GeneratedJmhSources,
    #     GenerateJmhSourcesRequest(
    #         request.field_set.address, jdk, jmh_classpath, classpath, files.snapshot.digest
    #     ),
    # )
    input_digest = await Get(Digest, MergeDigests([*classpath.digests(), files.snapshot.digest]))

    toolcp_relpath = "__toolcp"
    extra_immutable_input_digests = {
        toolcp_relpath: jmh_classpath.digest,
    }

    reports_dir_prefix = "__reports"
    reports_dir = os.path.join(reports_dir_prefix, request.field_set.address.path_safe_spec)

    # Classfiles produced by the root `jmh_test` targets are the only ones which should run.
    user_benchmarks = " ".join(classpath.root_args())

    # Cache bench runs only if they are successful, or not at all if `--bench-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if bench_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    field_set_extra_env = await Get(
        EnvironmentVars, EnvironmentVarsRequest(request.field_set.extra_env_vars.value or ())
    )

    process = JvmProcess(
        jdk=jdk,
        classpath_entries=[
            *classpath.args(),
            *jmh_classpath.classpath_entries(toolcp_relpath),
        ],
        argv=[
            "org.openjdk.jmh.Main",
            "-rff",
            reports_dir,
            *jmh.args,
            user_benchmarks,
        ],
        input_digest=input_digest,
        extra_env={**bench_extra_env.env, **field_set_extra_env},
        extra_jvm_options=jmh.jvm_options,
        extra_immutable_input_digests=extra_immutable_input_digests,
        output_directories=(reports_dir_prefix,),
        description=f"Run JMH benchmarks for {request.field_set.address}",
        timeout_seconds=request.field_set.timeout.calculate_from_global_options(bench_subsystem),
        level=LogLevel.DEBUG,
        cache_scope=cache_scope,
        use_nailgun=False,
    )
    return JmhSetup(process=process, reports_dir_prefix=reports_dir_prefix)


@rule(desc="Run JMH", level=LogLevel.DEBUG)
async def run_jmh_benchmark(
    bench_subsystem: BenchmarkSubsystem,
    batch: JmhBenchmarkRequest.Batch[JmhBenchmarkFieldSet, Any],
) -> BenchmarkResult:
    field_set = batch.single_element

    jmh_setup = await Get(JmhSetup, JmhSetupRequest(field_set))
    process_result = await Get(FallibleProcessResult, JvmProcess, jmh_setup.process)
    reports_dir_prefix = jmh_setup.reports_dir_prefix

    reports_subset = await Get(
        Digest,
        DigestSubset(
            process_result.output_digest, PathGlobs([os.path.join(reports_dir_prefix, "**")])
        ),
    )
    reports_snapshot = await Get(Snapshot, RemovePrefix(reports_subset, reports_dir_prefix))

    return BenchmarkResult.from_fallible_process_result(
        process_result,
        address=field_set.address,
        output_setting=bench_subsystem.output,
        reports=reports_snapshot,
    )


# @rule(level=LogLevel.DEBUG)
# async def generate_jmh_sources(request: GenerateJmhSourcesRequest, jmh: Jmh) -> GeneratedJmhSources:
#     input_prefix = "__input"
#     input_digest = await Get(
#         Digest, MergeDigests([*request.classpath.digests(), request.extra_files])
#     )

#     toolcp_relpath = "__toolcp"
#     extra_immutable_input_digests = {
#         toolcp_relpath: request.jmh_classpath.digest,
#         input_prefix: input_digest,
#     }

#     sources_output_dir = os.path.join("__gen", "sources")
#     files_output_dir = os.path.join("__gen", "files")
#     empty_dirs_digest = await Get(
#         Digest, CreateDigest([Directory(sources_output_dir), Directory(files_output_dir)])
#     )

#     process_result = await Get(
#         ProcessResult,
#         JvmProcess(
#             jdk=request.jdk,
#             classpath_entries=[
#                 *request.classpath.args(),
#                 *request.jmh_classpath.classpath_entries(toolcp_relpath),
#             ],
#             argv=[
#                 "org.openjdk.jmh.generators.bytecode.JmhBytecodeGenerator",
#                 input_prefix,
#                 sources_output_dir,
#                 files_output_dir,
#                 jmh.generator_type.value,
#             ],
#             input_digest=empty_dirs_digest,
#             extra_jvm_options=jmh.jvm_options,
#             extra_immutable_input_digests=extra_immutable_input_digests,
#             output_directories=(sources_output_dir, files_output_dir),
#             description=f"Generate JMH sources for {request.address}",
#             level=LogLevel.DEBUG,
#             use_nailgun=False,
#         ),
#     )

#     generated_digest = await Get(Digest, RemovePrefix(process_result.output_digest, "__gen"))
#     return GeneratedJmhSources(generated_digest)


@rule
def generate_jmh_lockfile_request(
    _: JmhToolLockfileSentinel, jmh: Jmh
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(jmh)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        *JmhBenchmarkRequest.rules(),
        UnionRule(GenerateToolLockfileSentinel, JmhToolLockfileSentinel),
    ]
