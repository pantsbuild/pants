# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib.resources
import itertools

from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, CoarsenedTargets
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolBase, GenerateJvmLockfileFromTool
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class AmmoniteSubsystem(JvmToolBase):
    options_scope = "ammonite"

    # TODO: Get this from a `ScalaToolBase` intermediate base class.
    SCALA_VERSION = "2.13.6"

    default_version = "2.4.1"
    default_artifacts = (
        f"com.lihaoyi:ammonite_{SCALA_VERSION}:{{version}}",
        f"com.lihaoyi:ammonite-repl_{SCALA_VERSION}:{{version}}",
    )
    default_lockfile_resource = ("pants.backend.scala.goals", "ammonite.default.lockfile.txt")
    default_lockfile_url = git_url(
        "src/python/pants/backend/scala/goals/ammonite.default.lockfile.txt"
    )


class AmmoniteReplToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = AmmoniteSubsystem.options_scope


class AmmoniteRepl(ReplImplementation):
    name = "ammonite"


class AmmoniteRunnerClassfiles(ClasspathEntry):
    pass


@rule(level=LogLevel.DEBUG)
async def create_scala_repl_request(
    request: AmmoniteRepl,
    bash: BashBinary,
    ammonite: AmmoniteSubsystem,
    runner_classfiles: AmmoniteRunnerClassfiles,
) -> ReplRequest:
    user_classpath, lockfile_request = await MultiGet(
        Get(Classpath, Addresses, request.addresses),
        Get(
            GenerateJvmLockfileFromTool, AmmoniteReplToolLockfileSentinel()
        )
    )

    roots = await Get(CoarsenedTargets, Addresses, request.addresses)
    environs = await MultiGet(
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_target(target)) for target in roots
    )
    jdk = max(environs, key=lambda j: j.jre_major_version)

    tool_classpath = await Get(
        ToolClasspath,
        ToolClasspathRequest(
            prefix="__toolcp",
            lockfile=lockfile_request,
        )
    )

    user_classpath_prefix = "__cp"
    prefixed_user_classpath = await MultiGet(
        Get(Digest, AddPrefix(d, user_classpath_prefix)) for d in user_classpath.digests()
    )

    # TODO: Manually merging the `immutable_input_digests` since InteractiveProcess doesn't
    # support them yet. See https://github.com/pantsbuild/pants/issues/13852.
    jdk_digests = await MultiGet(
        Get(Digest, AddPrefix(digest, relpath))
        for relpath, digest in jdk.immutable_input_digests.items()
    )

    repl_digest = await Get(
        Digest,
        MergeDigests([*prefixed_user_classpath, tool_classpath.content.digest, *jdk_digests]),
    )

    ss = await Get(Snapshot, Digest, repl_digest)
    print(f"DIGEST: {ss.files}")

    return ReplRequest(
        digest=repl_digest,
        args=[
            *jdk.args(
                bash,
                [
                    *tool_classpath.classpath_entries(),
                    *user_classpath.classpath_entries(user_classpath_prefix),
                ],
            ),
            "-Dscala.usejavacp=true",
            "ammonite.integration.AmmoniteRunner",
        ],
        extra_env=jdk.env,
        run_in_workspace=False,
        append_only_caches=jdk.append_only_caches,
    )


@rule
async def generate_ammonite_lockfile_request(
    _: AmmoniteReplToolLockfileSentinel, ammonite: AmmoniteSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.from_tool(ammonite)


@rule
async def setup_ammonite_runner_classfiles(
    bash: BashBinary, ammonite: AmmoniteSubsystem
) -> AmmoniteRunnerClassfiles:
    dest_dir = "classfiles"

    runner_source_content = importlib.resources.read_binary(
        "pants.backend.scala.goals", "AmmoniteRunner.scala"
    )
    if not runner_source_content:
        raise AssertionError("Unable to find AmmoniteRunner.scala resource.")

    runner_source = FileContent("AmmoniteRunner.scala", runner_source_content)

    lockfile_request = await Get(
        GenerateJvmLockfileFromTool, AmmoniteReplToolLockfileSentinel()
    )

    tool_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__toolcp",
                lockfile=lockfile_request,
            ),
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    runner_source,
                    Directory(dest_dir),
                ]
            ),
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                tool_classpath.digest,
                jdk_setup.digest,
                source_digest,
            )
        ),
    )

    # NB: We do not use nailgun for this process, since it is launched exactly once.
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, tool_classpath.classpath_entries()),
                "scala.tools.nsc.Main",
                "-bootclasspath",
                ":".join(tool_classpath.classpath_entries()),
                "-d",
                dest_dir,
                runner_source.path,
            ],
            input_digest=merged_digest,
            append_only_caches=jdk_setup.append_only_caches,
            env=jdk_setup.env,
            output_directories=(dest_dir,),
            description="Compile Ammonite repl runner with scalac",
            level=LogLevel.DEBUG,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return AmmoniteRunnerClassfiles(digest=stripped_classfiles_digest)


@rule
def generate_ammonite_lockfile_request(
    _: AmmoniteReplToolLockfileSentinel, tool: AmmoniteSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, AmmoniteReplToolLockfileSentinel),
        UnionRule(ReplImplementation, AmmoniteRepl),
    ]
