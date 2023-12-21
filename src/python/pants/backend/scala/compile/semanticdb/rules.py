# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.scala.compile import scalac_plugins
from pants.backend.scala.compile.scalac_plugins import (
    GlobalScalacPlugin,
    GlobalScalacPlugins,
    GlobalScalacPluginsRequest,
)
from pants.backend.scala.compile.semanticdb.subsystem import SemanticDbSubsystem
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.util_rules.versions import ScalaCrossVersionMode
from pants.engine.rules import collect_rules, rule
from pants.jvm.resolve.common import Coordinate

logger = logging.getLogger(__name__)


class ScalafixSemanticDBPluginsRequest(GlobalScalacPluginsRequest):
    pass


@rule
async def scalafix_semanticdb_scalac_plugin(
    request: ScalafixSemanticDBPluginsRequest,
    scala: ScalaSubsystem,
    semanticdb: SemanticDbSubsystem,
) -> GlobalScalacPlugins:
    if not semanticdb.enabled:
        return GlobalScalacPlugins([])

    scala_version = scala.version_for_resolve(request.resolve_name)
    if scala_version.major == 3:
        # TODO figure out how to pass semanticdb options to Scalac 3
        return GlobalScalacPlugins(
            [
                GlobalScalacPlugin(
                    name="semanticdb",
                    subsystem=semanticdb.options_scope,
                    coordinate=None,
                    extra_scalac_options=("-Xsemanticdb",),
                )
            ]
        )

    semanticdb_version = semanticdb.version_for(request.resolve_name, scala_version)
    if not semanticdb_version:
        logger.warn(
            f"Found no compatible version of `semanticdb-scalac` for Scala version '{scala_version}'."
        )
        return GlobalScalacPlugins([])

    scala_binary_version = scala_version.crossversion(ScalaCrossVersionMode.FULL)
    return GlobalScalacPlugins(
        [
            GlobalScalacPlugin(
                name="semanticdb",
                subsystem=semanticdb.options_scope,
                coordinate=Coordinate(
                    group="org.scalameta",
                    artifact=f"semanticdb-scalac_{scala_binary_version}",
                    version=semanticdb_version,
                ),
                extra_scalac_options=(
                    "-Yrangepos",
                    *(
                        f"-P:semanticdb:{name}:{value}"
                        for name, value in semanticdb.extra_options.items()
                    ),
                ),
            )
        ]
    )


def rules():
    return [
        *collect_rules(),
        *scalac_plugins.rules(),
        *ScalafixSemanticDBPluginsRequest.rules(),
    ]
