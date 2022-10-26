# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase
from pants.util.docutil import git_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


class JarDuplicateAction(Enum):
    SKIP = "skip"
    REPLACE = "replace"
    CONCAT = "concat"
    CONCAT_TEXT = "concat_text"
    THROW = "throw"


class JarTool(JvmToolBase):
    options_scope = "jar-tool"
    help = ""

    default_version = "0.0.17"
    default_artifacts = ("org.pantsbuild:jar-tool:{version}",)
    default_lockfile_resource = ("pants.jvm.jar_tool", "jar_tool.default.lockfile.txt")
    default_lockfile_path = "src/python/pants/jvm/jar_tool/jar_tool.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)


class JarToolGenerateLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = JarTool.options_scope


@rule
async def generate_jartool_lockfile_request(
    _: JarToolGenerateLockfileSentinel, jar_tool: JarTool
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(jar_tool)


@dataclass(unsafe_hash=True)
@frozen_after_init
class JarToolRequest:
    jar_name: str
    main_class: str | None
    classpath_entries: tuple[str, ...]
    manifest: str | None
    jars: tuple[str, ...]
    policies: FrozenDict[str, JarDuplicateAction]
    compress: bool
    digest: Digest

    def __init__(
        self,
        *,
        jar_name: str,
        digest: Digest,
        main_class: str | None = None,
        classpath_entries: Iterable[str] | None = None,
        manifest: str | None = None,
        jars: Iterable[str] | None = None,
        policies: Mapping[str, str | JarDuplicateAction] | None = None,
        compress: bool = True,
    ) -> None:
        self.jar_name = jar_name
        self.digest = digest
        self.main_class = main_class
        self.manifest = manifest
        self.classpath_entries = tuple(classpath_entries or ())
        self.jars = tuple(jars or ())
        self.policies = FrozenDict(JarToolRequest.__parse_policies(policies or {}))
        self.compress = compress

    @staticmethod
    def __parse_policies(
        policies: Mapping[str, str | JarDuplicateAction]
    ) -> dict[str, JarDuplicateAction]:
        return {
            pattern: action
            if isinstance(action, JarDuplicateAction)
            else JarDuplicateAction(action.lower())
            for pattern, action in policies.items()
        }


_JAR_TOOL_MAIN_CLASS = "org.pantsbuild.tools.jar.Main"


@rule
async def run_jar_tool(request: JarToolRequest, jdk: InternalJdk, jar_tool: JarTool) -> Digest:
    output_prefix = "__out"
    output_jarname = os.path.join(output_prefix, request.jar_name)

    lockfile_request, output_digest = await MultiGet(
        Get(GenerateJvmLockfileFromTool, JarToolGenerateLockfileSentinel()),
        Get(Digest, CreateDigest([Directory(output_prefix)])),
    )

    tool_classpath, input_digest = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(Digest, MergeDigests([request.digest, output_digest])),
    )

    toolcp_prefix = "__toolcp"
    immutable_input_digests = {toolcp_prefix: tool_classpath.digest}

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                _JAR_TOOL_MAIN_CLASS,
                *(("-main", request.main_class) if request.main_class else ()),
                *(
                    ("-classpath", ",".join(request.classpath_entries))
                    if request.classpath_entries
                    else ()
                ),
                *(("-manifest", request.manifest) if request.manifest else ()),
                *(("-jars", ",".join(request.jars)) if request.jars else ()),
                *(
                    (
                        "-policies",
                        ",".join(
                            f"{pattern}={action.value.upper()}"
                            for pattern, action in request.policies.items()
                        ),
                    )
                    if request.policies
                    else ()
                ),
                *(("-compress",) if request.compress else ()),
                output_jarname,
            ],
            classpath_entries=tool_classpath.classpath_entries(toolcp_prefix),
            input_digest=input_digest,
            extra_jvm_options=jar_tool.jvm_options,
            extra_immutable_input_digests=immutable_input_digests,
            description=f"Building jar {request.jar_name}",
            level=LogLevel.DEBUG,
        ),
    )

    return await Get(Digest, RemovePrefix(result.output_digest, output_prefix))


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, JarToolGenerateLockfileSentinel),
    ]
