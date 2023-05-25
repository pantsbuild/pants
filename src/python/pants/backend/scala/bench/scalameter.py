# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pants.backend.scala.subsystems.scalameter import Scalameter
from pants.backend.scala.target_types import (
    ScalaDependenciesField,
    ScalameterBenchmarkExtraEnvVarsField,
    ScalameterBenchmarkSourceField,
    ScalameterBenchmarkTimeoutField,
)
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
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Addresses
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix, Snapshot
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, SourcesField, Targets
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.target_types import JvmJdkField
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class ScalameterBenchmarkFieldSet(BenchmarkFieldSet):
    """The fields necessary to run benchmarks on a target."""

    required_fields = (ScalameterBenchmarkSourceField, JvmJdkField)

    sources: ScalameterBenchmarkSourceField
    dependencies: ScalaDependenciesField
    timeout: ScalameterBenchmarkTimeoutField
    extra_env_vars: ScalameterBenchmarkExtraEnvVarsField
    jdk_version: JvmJdkField


class ScalameterBenchmarkRequest(BenchmarkRequest):
    tool_subsystem = Scalameter
    field_set_type = ScalameterBenchmarkFieldSet


class ScalameterToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Scalameter.options_scope


@dataclass(frozen=True)
class ScalameterSetupRequest:
    field_set: ScalameterBenchmarkFieldSet


@dataclass(frozen=True)
class ScalameterSetup:
    process: JvmProcess
    results_dir_prefix: str


async def _benchmark_classnames(field_set: ScalameterBenchmarkFieldSet) -> list[str]:
    """Determine fully classified names of the benchmark classes in the given field set."""

    stripped_sources = await Get(
        StrippedSourceFiles,
        SourceFilesRequest([field_set.sources]),
    )

    def classname_from_file(file: str) -> str:
        ext_index = file.index(".scala")
        classname = file[:ext_index].replace(os.path.sep, ".")
        return classname

    return [classname_from_file(file) for file in stripped_sources.snapshot.files]


@rule(LogLevel.DEBUG)
async def setup_scalameter_for_target(
    request: ScalameterSetupRequest,
    scalameter: Scalameter,
    bench_subsystem: BenchmarkSubsystem,
    bench_extra_env: BenchmarkExtraEnv,
) -> ScalameterSetup:
    jdk, dependencies = await MultiGet(
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_field(request.field_set.jdk_version)),
        Get(Targets, DependenciesRequest(request.field_set.dependencies)),
    )

    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScalameterToolLockfileSentinel())
    classpath, scalameter_classpath, files = await MultiGet(
        Get(Classpath, Addresses([request.field_set.address])),
        Get(
            ToolClasspath,
            ToolClasspathRequest(lockfile=lockfile_request),
        ),
        Get(
            SourceFiles,
            SourceFilesRequest(
                (dep.get(SourcesField) for dep in dependencies),
                for_sources_types=(FileSourceField,),
                enable_codegen=True,
            ),
        ),
    )

    input_digest = await Get(Digest, MergeDigests([*classpath.digests(), files.snapshot.digest]))

    toolcp_relpath = "__toolcp"
    immutable_input_digests = {
        toolcp_relpath: scalameter_classpath.digest,
    }

    reports_dir_prefix = "__reports"
    reports_dir = os.path.join(reports_dir_prefix, request.field_set.address.path_safe_spec)

    benchmark_classnames = await _benchmark_classnames(request.field_set)

    # Cache test runs only if they are successful, or not at all if `--bench-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if bench_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    field_set_extra_env = await Get(
        EnvironmentVars, EnvironmentVarsRequest(request.field_set.extra_env_vars.value or ())
    )

    args = ["org.scalameter.Main", "-CresultDir", reports_dir]
    if benchmark_classnames:
        args.extend(["-b", ":".join(benchmark_classnames)])
    if scalameter.min_warmups:
        args.extend(["-Cminwarmpus", str(scalameter.min_warmups)])
    if scalameter.max_warmups:
        args.extend(["-Cmaxwarmups", str(scalameter.max_warmups)])
    if scalameter.runs:
        args.extend(["-Cruns", str(scalameter.runs)])
    if scalameter.colors is not None:
        args.extend(["-Ccolors", "true" if scalameter.colors else "false"])

    process = JvmProcess(
        jdk=jdk,
        argv=args,
        classpath_entries=[
            *classpath.args(),
            *scalameter_classpath.classpath_entries(toolcp_relpath),
        ],
        input_digest=input_digest,
        extra_env={**bench_extra_env.env, **field_set_extra_env},
        extra_jvm_options=scalameter.jvm_options,
        extra_immutable_input_digests=immutable_input_digests,
        output_directories=(reports_dir,),
        description=f"Run ScalaMeter for {request.field_set.address}",
        timeout_seconds=request.field_set.timeout.calculate_from_global_options(bench_subsystem),
        use_nailgun=False,
        level=LogLevel.DEBUG,
        cache_scope=cache_scope,
    )
    return ScalameterSetup(process, reports_dir_prefix)


@rule(desc="Run ScalaMeter", level=LogLevel.DEBUG)
async def run_scalameter_benchmark(
    bench_subsystem: BenchmarkSubsystem,
    batch: ScalameterBenchmarkRequest.Batch[ScalameterBenchmarkFieldSet, Any],
) -> BenchmarkResult:
    field_set = batch.single_element

    bench_setup = await Get(ScalameterSetup, ScalameterSetupRequest(field_set))
    process_result = await Get(FallibleProcessResult, JvmProcess, bench_setup.process)
    results_dir_prefix = bench_setup.results_dir_prefix

    reports_digest = await Get(
        Digest,
        DigestSubset(process_result.output_digest, PathGlobs([f"{results_dir_prefix}/**"])),
    )
    reports_snapshot = await Get(Snapshot, RemovePrefix(reports_digest, results_dir_prefix))

    return BenchmarkResult.from_fallible_process_result(
        process_result,
        address=field_set.address,
        output_setting=bench_subsystem.output,
        reports=reports_snapshot,
    )


@rule
async def generate_scalameter_lockfile_request(
    _: ScalameterToolLockfileSentinel, scalameter: Scalameter
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(scalameter)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        *ScalameterBenchmarkRequest.rules(),
        UnionRule(GenerateToolLockfileSentinel, ScalameterToolLockfileSentinel),
    ]
