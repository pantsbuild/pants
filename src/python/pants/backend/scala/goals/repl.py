# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    resolve_scala_artifacts_for_version,
)
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, MergeDigests
from pants.engine.internals.graph import coarsened_targets
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import add_prefix, merge_digests
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.jvm.classpath import classpath
from pants.jvm.jdk_rules import JdkRequest, prepare_jdk_environment
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import ToolClasspathRequest, materialize_classpath_for_tool
from pants.util.logging import LogLevel


class ScalaRepl(ReplImplementation):
    name = "scala"
    supports_args = False


@rule(level=LogLevel.DEBUG)
async def create_scala_repl_request(
    request: ScalaRepl, bash: BashBinary, scala_subsystem: ScalaSubsystem
) -> ReplRequest:
    user_classpath = await classpath(**implicitly({request.addresses: Addresses}))

    roots = await coarsened_targets(**implicitly({request.addresses: Addresses}))
    environs = await concurrently(
        prepare_jdk_environment(**implicitly({JdkRequest.from_target(target): JdkRequest}))
        for target in roots
    )
    jdk = max(environs, key=lambda j: j.jre_major_version)

    scala_version = scala_subsystem.version_for_resolve(user_classpath.resolve.name)
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(scala_version)
    )
    tool_classpath = await materialize_classpath_for_tool(
        ToolClasspathRequest(
            prefix="__toolcp",
            artifact_requirements=ArtifactRequirements.from_coordinates(
                scala_artifacts.all_coordinates
            ),
        )
    )

    user_classpath_prefix = "__cp"
    prefixed_user_classpath = await concurrently(
        add_prefix(AddPrefix(d, user_classpath_prefix)) for d in user_classpath.digests()
    )

    repl_digest = await merge_digests(
        MergeDigests([*prefixed_user_classpath, tool_classpath.content.digest])
    )

    return ReplRequest(
        digest=repl_digest,
        args=[
            *jdk.args(bash, tool_classpath.classpath_entries(), chroot="{chroot}"),
            "-Dscala.usejavacp=true",
            scala_artifacts.repl_main,
            "-classpath",
            ":".join(user_classpath.args(prefix=user_classpath_prefix)),
        ],
        run_in_workspace=False,
        extra_env={
            **jdk.env,
            "PANTS_INTERNAL_ABSOLUTE_PREFIX": "",
        },
        immutable_input_digests=jdk.immutable_input_digests,
        append_only_caches=jdk.append_only_caches,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ReplImplementation, ScalaRepl),
    )
