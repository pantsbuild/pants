# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum, unique
from typing import Iterable, Mapping

from pants.backend.openapi.subsystems import openapi_generator
from pants.backend.openapi.subsystems.openapi_generator import (
    OpenAPIGenerator,
    OpenAPIGeneratorLockfileSentinel,
)
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm import jdk_rules, non_jvm_dependencies
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.util_rules import rules as jvm_util_rules
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@unique
class OpenAPIGeneratorType(Enum):
    JAVA = "java"


@dataclass(frozen=True)
class OpenAPIGeneratorProcess:
    argv: tuple[str, ...]
    generator_type: OpenAPIGeneratorType
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_env: FrozenDict[str, str]
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_classpath_entries: tuple[str, ...]
    extra_jvm_options: tuple[str, ...]
    cache_scope: ProcessCacheScope | None
    output_directories: tuple[str, ...]
    output_files: tuple[str, ...]

    def __init__(
        self,
        *,
        generator_type: OpenAPIGeneratorType,
        argv: Iterable[str],
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        output_directories: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_classpath_entries: Iterable[str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_jvm_options: Iterable[str] | None = None,
        cache_scope: ProcessCacheScope | None = None,
    ):
        object.__setattr__(self, "generator_type", generator_type)
        object.__setattr__(self, "argv", tuple(argv))
        object.__setattr__(self, "input_digest", input_digest)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "output_directories", tuple(output_directories or ()))
        object.__setattr__(self, "output_files", tuple(output_files or ()))
        object.__setattr__(self, "extra_env", FrozenDict(extra_env or {}))
        object.__setattr__(self, "extra_classpath_entries", tuple(extra_classpath_entries or ()))
        object.__setattr__(
            self, "extra_immutable_input_digests", FrozenDict(extra_immutable_input_digests or {})
        )
        object.__setattr__(self, "extra_jvm_options", tuple(extra_jvm_options or ()))
        object.__setattr__(self, "cache_scope", cache_scope)


_GENERATOR_CLASS_NAME = "org.openapitools.codegen.OpenAPIGenerator"


@rule
async def openapi_generator_process(
    request: OpenAPIGeneratorProcess, jdk: InternalJdk, subsystem: OpenAPIGenerator
) -> Process:
    lockfile_request = await Get(GenerateJvmLockfileFromTool, OpenAPIGeneratorLockfileSentinel())
    tool_classpath = await Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request))

    toolcp_relpath = "__toolcp"
    immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        **request.extra_immutable_input_digests,
    }

    classpath_entries = [
        *tool_classpath.classpath_entries(toolcp_relpath),
        *request.extra_classpath_entries,
    ]

    extra_jvm_options = [*subsystem.jvm_options, *request.extra_jvm_options]

    jvm_process = JvmProcess(
        jdk=jdk,
        argv=[
            _GENERATOR_CLASS_NAME,
            "generate",
            "-g",
            request.generator_type.value,
            *request.argv,
        ],
        classpath_entries=classpath_entries,
        input_digest=request.input_digest,
        extra_env=request.extra_env,
        extra_immutable_input_digests=immutable_input_digests,
        extra_jvm_options=extra_jvm_options,
        description=request.description,
        level=request.level,
        output_directories=request.output_directories,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
    )
    return await Get(Process, JvmProcess, jvm_process)


def rules():
    return [
        *collect_rules(),
        *openapi_generator.rules(),
        *coursier_setup.rules(),
        *coursier_fetch.rules(),
        *jvm_tool.rules(),
        *jdk_rules.rules(),
        *non_jvm_dependencies.rules(),
        *jvm_util_rules(),
    ]
