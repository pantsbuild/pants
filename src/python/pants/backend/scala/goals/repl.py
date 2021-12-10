# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools

from pants.backend.scala.compile.scala_subsystem import ScalaSubsystem
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import BashBinary
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.util.logging import LogLevel


class ScalaRepl(ReplImplementation):
    name = "scala"


@rule(level=LogLevel.DEBUG)
async def create_scala_repl_request(
    repl: ScalaRepl, bash: BashBinary, jdk_setup: JdkSetup, scala_subsystem: ScalaSubsystem
) -> ReplRequest:
    dependencies_for_each_target = await MultiGet(
        Get(Addresses, DependenciesRequest(tgt[Dependencies])) for tgt in repl.targets
    )
    dependencies = list(itertools.chain.from_iterable(dependencies_for_each_target))

    user_classpath, tool_classpath = await MultiGet(
        Get(Classpath, Addresses(dependencies)),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=(
                    ArtifactRequirements.from_coordinates(
                        [
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-compiler",
                                version=scala_subsystem.version,
                            ),
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-library",
                                version=scala_subsystem.version,
                            ),
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-reflect",
                                version=scala_subsystem.version,
                            ),
                        ]
                    ),
                ),
            ),
        ),
    )

    user_classpath_prefix = "__cp"
    prefixed_user_classpath = await Get(
        Digest, AddPrefix(user_classpath.content.digest, user_classpath_prefix)
    )

    repl_digest = await Get(
        Digest,
        MergeDigests([prefixed_user_classpath, tool_classpath.content.digest, jdk_setup.digest]),
    )

    return ReplRequest(
        digest=repl_digest,
        args=[
            *jdk_setup.args(bash, tool_classpath.classpath_entries()),
            "-Dscala.usejavacp=true",
            "scala.tools.nsc.MainGenericRunner",
            "-classpath",
            ":".join(user_classpath.classpath_entries(user_classpath_prefix)),
        ],
        extra_env=jdk_setup.env,
        run_in_workspace=False,
        append_only_caches=jdk_setup.append_only_caches,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ReplImplementation, ScalaRepl),
    )
