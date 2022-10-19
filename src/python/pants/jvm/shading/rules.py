# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from os import path
from pathlib import PurePath
from typing import Iterable

from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.shading import jarjar
from pants.jvm.shading.jarjar import JarJar, JarJarGeneratorLockfileSentinel, MisplacedClassStrategy
from pants.jvm.target_types import JarShadingRule
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(unsafe_hash=True)
@frozen_after_init
class ShadeJarRequest:
    path: PurePath
    digest: Digest
    rules: tuple[JarShadingRule, ...]

    # JarJar configuration options
    skip_manifest: bool
    misplaced_class_strategy: MisplacedClassStrategy | None
    verbose: bool

    def __init__(
        self,
        *,
        path: str | PurePath,
        digest: Digest,
        rules: Iterable[JarShadingRule] | None = None,
        skip_manifest: bool = False,
        misplaced_class_strategy: MisplacedClassStrategy | None = None,
        verbose: bool = False
    ) -> None:
        self.path = path if isinstance(path, PurePath) else PurePath(path)
        self.digest = digest
        self.rules = tuple(rules or ())
        self.skip_manifest = skip_manifest
        self.misplaced_class_strategy = misplaced_class_strategy
        self.verbose = verbose


@dataclass(frozen=True)
class ShadedJar:
    path: str
    digest: Digest


_JARJAR_MAIN_CLASS = "com.eed3si9n.jarjar.Main"
_JARJAR_RULE_CONFIG_FILENAME = "__jarjar.rules"


@rule(desc="Applies shading rules to a JAR file")
async def shade_jar(request: ShadeJarRequest, jdk: InternalJdk, jarjar: JarJar) -> ShadedJar:
    if not request.rules:
        return ShadedJar(path=str(request.path), digest=request.digest)

    output_prefix = "__out"
    output_filename = path.join(output_prefix, request.path.name)

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
        "verbose": str(request.verbose or jarjar.verbose),
        "skipManifest": str(request.skip_manifest or jarjar.skip_manifest),
    }
    if request.misplaced_class_strategy or jarjar.misplaced_class_strategy:
        system_properties["misplacedClassStrategy"] = (
            request.misplaced_class_strategy.value or jarjar.misplaced_class_strategy.value
        )

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                _JARJAR_MAIN_CLASS,
                "process",
                _JARJAR_RULE_CONFIG_FILENAME,
                str(request.path),
                output_filename,
            ],
            classpath_entries=tool_classpath.classpath_entries(toolcp_prefix),
            input_digest=input_digest,
            extra_immutable_input_digests=immutable_input_digests,
            extra_jvm_options=[
                *jarjar.jvm_options,
                *[f"-D{prop}={value}" for prop, value in system_properties.items()],
            ],
            description=f"Shading JAR {request.path}",
            output_directories=(output_prefix,),
            level=LogLevel.DEBUG,
        ),
    )

    shaded_jar_digest = await Get(Digest, RemovePrefix(result.output_digest, output_prefix))
    if request.path.parents:
        # Restore the folder structure of the original path in the output digest
        shaded_jar_digest = await Get(
            Digest, AddPrefix(shaded_jar_digest, str(request.path.parent))
        )

    return ShadedJar(path=str(request.path), digest=shaded_jar_digest)


def rules():
    return [*collect_rules(), *jarjar.rules()]
