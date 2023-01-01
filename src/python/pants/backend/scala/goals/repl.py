# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTargets
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.util.logging import LogLevel


class ScalaRepl(ReplImplementation):
    name = "scala"


@rule(level=LogLevel.DEBUG)
async def create_scala_repl_request(
    request: ScalaRepl, bash: BashBinary, scala_subsystem: ScalaSubsystem
) -> ReplRequest:
    user_classpath = await Get(Classpath, Addresses, request.addresses)

    roots = await Get(CoarsenedTargets, Addresses, request.addresses)
    environs = await MultiGet(
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_target(target)) for target in roots
    )
    jdk = max(environs, key=lambda j: j.jre_major_version)

    scala_version = scala_subsystem.version_for_resolve(user_classpath.resolve.name)
    tool_classpath = await Get(
        ToolClasspath,
        ToolClasspathRequest(
            prefix="__toolcp",
            artifact_requirements=ArtifactRequirements.from_coordinates(
                [
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-compiler",
                        version=scala_version,
                    ),
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-library",
                        version=scala_version,
                    ),
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-reflect",
                        version=scala_version,
                    ),
                ]
            ),
        ),
    )

    user_classpath_prefix = "__cp"
    prefixed_user_classpath = await MultiGet(
        Get(Digest, AddPrefix(d, user_classpath_prefix)) for d in user_classpath.digests()
    )

    repl_digest = await Get(
        Digest,
        MergeDigests([*prefixed_user_classpath, tool_classpath.content.digest]),
    )

    return ReplRequest(
        digest=repl_digest,
        args=[
            *jdk.args(bash, tool_classpath.classpath_entries(), chroot="{chroot}"),
            "-Dscala.usejavacp=true",
            "scala.tools.nsc.MainGenericRunner",
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
