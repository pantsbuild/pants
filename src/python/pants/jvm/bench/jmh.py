# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations
from dataclasses import dataclass
from pants.backend.java.subsystems.jmh import Jmh

from pants.core.goals.bench import BenchmarkFieldSet, BenchmarkRequest
from pants.jvm.jdk_rules import JvmProcess
from pants.jvm.resolve.jvm_tool import GenerateJvmToolLockfileSentinel
from pants.jvm.target_types import JmhBenchmarkExtraEnvVarsField, JmhBenchmarkSourceField, JmhBenchmarkTimeoutField, JvmDependenciesField, JvmJdkField

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

class JmhTollLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = Jmh.options_scope

@dataclass(frozen=True)
class JmhSetupRequest:
    field_set: JmhBenchmarkFieldSet

@dataclass(frozen=True)
class JmhSetup:
    process: JvmProcess
    reports_dir_prefix: str
