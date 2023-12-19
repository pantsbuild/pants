# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
from pants.engine.unions import UnionRule
from pants.jvm.resolve.common import Coordinate


class ScalafixSemanticDBPluginsRequest(GlobalScalacPluginsRequest):
    pass


@rule
async def scalafix_semanticdb_scalac_plugin(
    request: ScalafixSemanticDBPluginsRequest,
    scala: ScalaSubsystem,
    semanticdb: SemanticDbSubsystem,
) -> GlobalScalacPlugins:
    scala_version = scala.version_for_resolve(request.resolve_name)
    scala_binary_version = scala_version.crossversion(ScalaCrossVersionMode.FULL)
    return GlobalScalacPlugins(
        [
            GlobalScalacPlugin(
                name="semanticdb",
                subsystem=semanticdb.options_scope,
                coordinate=Coordinate(
                    group="org.scalameta",
                    artifact=f"semanticdb-scalac_{scala_binary_version}",
                    version=semanticdb.version,
                ),
                extra_scalac_options=("-Yrangepos",),
            )
        ]
    )


def rules():
    return [
        *collect_rules(),
        *scalac_plugins.rules(),
        *ScalafixSemanticDBPluginsRequest.rules(),
    ]
