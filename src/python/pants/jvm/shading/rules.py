# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path
from typing import Iterable

from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests, RemovePrefix
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.shading import jarjar
from pants.jvm.shading.jarjar import JarJar, JarJarGeneratorLockfileSentinel
from pants.jvm.target_types import JarShadingRule
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(unsafe_hash=True)
@frozen_after_init
class ShadeJarRequest:
    filename: str
    digest: Digest
    rules: tuple[JarShadingRule, ...]

    def __init__(
        self, *, filename: str, digest: Digest, rules: Iterable[JarShadingRule] | None = None
    ) -> None:
        self.filename = filename
        self.digest = digest
        self.rules = tuple(rules or ())


@dataclass(frozen=True)
class ShadedJar:
    filename: str
    digest: Digest


_JARJAR_RULE_CONFIG_FILENAME = "__jarjar.rules"


@rule(desc="Applies shading rules to a JAR file")
async def shade_jar(request: ShadeJarRequest, jdk: InternalJdk, jarjar: JarJar) -> ShadedJar:
    if not request.rules:
        return ShadedJar(filename=request.filename, digest=request.digest)

    output_prefix = "__out"
    output_filename = path.join(output_prefix, path.basename(request.filename))

    rule_config_content = "\n".join([rule.encode() for rule in request.rules])
    logger.debug(f"Using JarJar rule file with following rules:\n{rule_config_content}")

    lockfile_request, tool_input_digest = await MultiGet(
        Get(GenerateJvmLockfileFromTool, JarJarGeneratorLockfileSentinel()),
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path=_JARJAR_RULE_CONFIG_FILENAME,
                        content=rule_config_content.encode("utf-8"),
                    ),
                    Directory(output_prefix),
                ]
            ),
        ),
    )

    tool_classpath, input_digest = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(Digest, MergeDigests([request.digest, tool_input_digest])),
    )

    toolcp_prefix = "__toolcp"
    immutable_input_digests = {toolcp_prefix: tool_classpath.digest}

    system_properties: dict[str, str] = {
        "verbose": str(jarjar.verbose),
        "skipManifest": str(jarjar.skip_manifest),
    }

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                "com.tonicsystems.jarjar.Main",
                "process",
                _JARJAR_RULE_CONFIG_FILENAME,
                request.filename,
                output_filename,
            ],
            classpath_entries=tool_classpath.classpath_entries(toolcp_prefix),
            input_digest=input_digest,
            extra_immutable_input_digests=immutable_input_digests,
            extra_jvm_options=[
                *jarjar.jvm_options,
                *[f"-D{prop}={value}" for prop, value in system_properties.items()],
            ],
            description=f"Shading JAR {request.filename}",
            output_directories=(output_prefix,),
            level=LogLevel.DEBUG,
        ),
    )

    shaded_jar_digest = await Get(Digest, RemovePrefix(result.output_digest, output_prefix))
    return ShadedJar(filename=path.basename(request.filename), digest=shaded_jar_digest)


def rules():
    return [*collect_rules(), *jarjar.rules()]
