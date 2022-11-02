# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum, unique
from typing import Iterable, Mapping

from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.fs import CreateDigest, Digest, Directory, RemovePrefix
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


@unique
class JarDuplicateAction(Enum):
    SKIP = "skip"
    REPLACE = "replace"
    CONCAT = "concat"
    CONCAT_TEXT = "concat_text"
    THROW = "throw"


class _JarTool(JvmToolBase):
    options_scope = "__jar-tool"
    help = "Pants' implementation of a JAR builder tool."

    default_version = "0.0.17"
    default_artifacts = ("org.pantsbuild:jar-tool:{version}",)
    default_lockfile_resource = ("pants.jvm.jar_tool", "jar_tool.default.lockfile.txt")
    default_lockfile_path = "src/python/pants/jvm/jar_tool/jar_tool.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)


class JarToolGenerateLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = _JarTool.options_scope


@rule
async def generate_jartool_lockfile_request(
    _: JarToolGenerateLockfileSentinel, jar_tool: _JarTool
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(jar_tool)


@dataclass(unsafe_hash=True)
@frozen_after_init
class JarToolRequest:
    jar_name: str
    digest: Digest
    main_class: str | None
    classpath_entries: tuple[str, ...]
    manifest: str | None
    jars: tuple[str, ...]
    file_mappings: FrozenDict[str, str]
    default_action: JarDuplicateAction | None
    policies: tuple[tuple[str, JarDuplicateAction], ...]
    skip: tuple[str, ...]
    compress: bool
    update: bool

    def __init__(
        self,
        *,
        jar_name: str,
        digest: Digest,
        main_class: str | None = None,
        classpath_entries: Iterable[str] | None = None,
        manifest: str | None = None,
        jars: Iterable[str] | None = None,
        file_mappings: Mapping[str, str] | None = None,
        default_action: JarDuplicateAction | None = None,
        policies: Iterable[tuple[str, str | JarDuplicateAction]] | None = None,
        skip: Iterable[str] | None = None,
        compress: bool = False,
        update: bool = False,
    ) -> None:
        self.jar_name = jar_name
        self.digest = digest
        self.main_class = main_class
        self.manifest = manifest
        self.classpath_entries = tuple(classpath_entries or ())
        self.jars = tuple(jars or ())
        self.file_mappings = FrozenDict(file_mappings or {})
        self.default_action = default_action
        self.policies = tuple(JarToolRequest.__parse_policies(policies or ()))
        self.skip = tuple(skip or ())
        self.compress = compress
        self.update = update

    @staticmethod
    def __parse_policies(
        policies: Iterable[tuple[str, str | JarDuplicateAction]]
    ) -> Iterable[tuple[str, JarDuplicateAction]]:
        return [
            (
                pattern,
                action
                if isinstance(action, JarDuplicateAction)
                else JarDuplicateAction(action.lower()),
            )
            for (pattern, action) in policies
        ]


_JAR_TOOL_MAIN_CLASS = "org.pantsbuild.tools.jar.Main"


@rule
async def run_jar_tool(request: JarToolRequest, jdk: InternalJdk, jar_tool: _JarTool) -> Digest:
    output_prefix = "__out"
    output_jarname = os.path.join(output_prefix, request.jar_name)

    lockfile_request, empty_output_digest = await MultiGet(
        Get(GenerateJvmLockfileFromTool, JarToolGenerateLockfileSentinel()),
        Get(Digest, CreateDigest([Directory(output_prefix)])),
    )

    tool_classpath = await Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request))

    toolcp_prefix = "__toolcp"
    input_prefix = "__in"
    immutable_input_digests = {toolcp_prefix: tool_classpath.digest, input_prefix: request.digest}

    policies = ",".join(
        f"{pattern}={action.value.upper()}" for (pattern, action) in request.policies
    )
    file_mappings = ",".join(
        f"{os.path.join(input_prefix, fs_path)}={jar_path}"
        for fs_path, jar_path in request.file_mappings.items()
    )

    tool_process = JvmProcess(
        jdk=jdk,
        argv=[
            _JAR_TOOL_MAIN_CLASS,
            output_jarname,
            *((f"-main={request.main_class}",) if request.main_class else ()),
            *(
                (f"-classpath={','.join(request.classpath_entries)}",)
                if request.classpath_entries
                else ()
            ),
            *(
                (f"-manifest={os.path.join(input_prefix, request.manifest)}",)
                if request.manifest
                else ()
            ),
            *(
                (f"-jars={','.join([os.path.join(input_prefix, jar) for jar in request.jars])}",)
                if request.jars
                else ()
            ),
            *((f"-files={file_mappings}",) if file_mappings else ()),
            *(
                (f"-default_action={request.default_action.value.upper()}",)
                if request.default_action
                else ()
            ),
            *((f"-policies={policies}",) if policies else ()),
            *((f"-skip={','.join(request.skip)}",) if request.skip else ()),
            *(("-compress",) if request.compress else ()),
            *(("-update",) if request.update else ()),
        ],
        classpath_entries=tool_classpath.classpath_entries(toolcp_prefix),
        input_digest=empty_output_digest,
        extra_jvm_options=jar_tool.jvm_options,
        extra_immutable_input_digests=immutable_input_digests,
        description=f"Building jar {request.jar_name}",
        output_directories=(output_prefix,),
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, JvmProcess, tool_process)
    return await Get(Digest, RemovePrefix(result.output_digest, output_prefix))


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, JarToolGenerateLockfileSentinel),
    ]
