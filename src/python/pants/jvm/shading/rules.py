# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.engine.engine_aware import EngineAwareParameter
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
from pants.jvm.shading.jarjar import JarJar, MisplacedClassStrategy
from pants.jvm.target_types import JvmShadingRule, _shading_validate_rules
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShadeJarRequest(EngineAwareParameter):
    path: PurePath
    digest: Digest
    rules: tuple[JvmShadingRule, ...]

    # JarJar configuration options
    skip_manifest: bool | None
    misplaced_class_strategy: MisplacedClassStrategy | None

    def __init__(
        self,
        *,
        path: str | PurePath,
        digest: Digest,
        rules: Iterable[JvmShadingRule] | None = None,
        skip_manifest: bool | None = None,
        misplaced_class_strategy: MisplacedClassStrategy | None = None,
    ) -> None:
        object.__setattr__(self, "path", path if isinstance(path, PurePath) else PurePath(path))
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "rules", tuple(rules or ()))
        object.__setattr__(self, "skip_manifest", skip_manifest)
        object.__setattr__(self, "misplaced_class_strategy", misplaced_class_strategy)

        self.__post_init__()

    def __post_init__(self):
        validation_errors = _shading_validate_rules(self.rules)
        if validation_errors:
            raise ValueError("\n".join(["Invalid rules provided:\n", *validation_errors]))

    def debug_hint(self) -> str | None:
        return str(self.path)


@dataclass(frozen=True)
class ShadedJar:
    path: str
    digest: Digest


_JARJAR_MAIN_CLASS = "com.eed3si9n.jarjar.Main"
_JARJAR_RULE_CONFIG_FILENAME = "rules"


@rule(desc="Applies shading rules to a JAR file")
async def shade_jar(request: ShadeJarRequest, jdk: InternalJdk, jarjar: JarJar) -> ShadedJar:
    if not request.rules:
        return ShadedJar(path=str(request.path), digest=request.digest)

    output_prefix = "__out"
    output_filename = os.path.join(output_prefix, request.path.name)

    rule_config_content = "\n".join([rule.encode() for rule in request.rules]) + "\n"
    logger.debug(f"Using JarJar rule file with following contents:\n{rule_config_content}")

    conf_digest, output_digest = await MultiGet(
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path=_JARJAR_RULE_CONFIG_FILENAME,
                        content=rule_config_content.encode("utf-8"),
                    ),
                ]
            ),
        ),
        Get(Digest, CreateDigest([Directory(output_prefix)])),
    )

    tool_classpath, input_digest = await MultiGet(
        Get(
            ToolClasspath, ToolClasspathRequest(lockfile=GenerateJvmLockfileFromTool.create(jarjar))
        ),
        Get(Digest, MergeDigests([request.digest, output_digest])),
    )

    toolcp_prefix = "__toolcp"
    conf_prefix = "__conf"
    immutable_input_digests = {
        toolcp_prefix: tool_classpath.digest,
        conf_prefix: conf_digest,
    }

    def should_skip_manifest() -> bool:
        if request.skip_manifest is not None:
            return request.skip_manifest
        return jarjar.skip_manifest

    system_properties: dict[str, str] = {
        "verbose": str(logger.isEnabledFor(LogLevel.DEBUG.level)).lower(),
        "skipManifest": str(should_skip_manifest()).lower(),
    }
    misplaced_class_strategy = request.misplaced_class_strategy or jarjar.misplaced_class_strategy
    if misplaced_class_strategy:
        system_properties["misplacedClassStrategy"] = misplaced_class_strategy.value

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                _JARJAR_MAIN_CLASS,
                "process",
                os.path.join(conf_prefix, _JARJAR_RULE_CONFIG_FILENAME),
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
