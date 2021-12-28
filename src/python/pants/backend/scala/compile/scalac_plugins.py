# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, cast

from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import (
    ScalacPluginArtifactField,
    ScalacPluginNameField,
    ScalacPluginTarget,
)
from pants.build_graph.address import AddressInput
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.resolve.coursier_fetch import (
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.jvm.resolve.jvm_tool import rules as jvm_tool_rules
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import bullet_list


@dataclass(frozen=True)
class _LoadedGlobalScalacPlugins:
    names: tuple[str, ...]
    artifact_address_inputs: tuple[str, ...]


@rule
async def parse_global_scalac_plugins(scalac_plugins: Scalac) -> _LoadedGlobalScalacPlugins:
    targets = await MultiGet(
        Get(WrappedTarget, AddressInput, AddressInput.parse(ai))
        for ai in scalac_plugins.plugins_global
    )

    artifact_address_inputs = []
    names = []
    invalid_targets = []
    for wrapped_target in targets:
        target = wrapped_target.target
        if target.has_field(ScalacPluginArtifactField):
            artifact_address_inputs.append(cast(str, target[ScalacPluginArtifactField].value))
            names.append(target.get(ScalacPluginNameField).value or target.address.target_name)
        else:
            invalid_targets.append(target)

    if invalid_targets:
        raise ValueError(
            f"The `[{Scalac.options_scope}].global` option accepts only "
            f"`{ScalacPluginTarget.alias}` targets, but got:\n\n"
            f"{bullet_list(type(t).alias for t in invalid_targets)}"
        )

    return _LoadedGlobalScalacPlugins(
        names=tuple(names), artifact_address_inputs=tuple(artifact_address_inputs)
    )


class GlobalScalacPluginsToolLockfileSentinel(JvmToolLockfileSentinel):
    resolve_name = "scalac-plugins"


@rule
def generate_global_scalac_plugins_lockfile_request(
    _: GlobalScalacPluginsToolLockfileSentinel,
    loaded_global_plugins: _LoadedGlobalScalacPlugins,
    scalac_plugins: Scalac,
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest(
        artifact_inputs=FrozenOrderedSet(loaded_global_plugins.artifact_address_inputs),
        resolve_name="scalac-plugins",
        lockfile_dest=scalac_plugins.plugins_global_lockfile,
    )


@dataclass(frozen=True)
class GlobalScalacPlugins:
    names: tuple[str, ...]
    classpath: MaterializedClasspath

    def args(self, prefix: str | None = None) -> Iterator[str]:
        for scalac_plugin_path in self.classpath.classpath_entries(prefix):
            yield f"-Xplugin:{scalac_plugin_path}"
        for name in self.names:
            yield f"-Xplugin-require:{name}"


@rule
async def global_scalac_plugins(
    loaded_global_plugins: _LoadedGlobalScalacPlugins,
) -> GlobalScalacPlugins:

    lockfile = await Get(CoursierResolvedLockfile, GlobalScalacPluginsToolLockfileSentinel())
    classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="__scalac_plugin_cp",
            lockfiles=(lockfile,),
        ),
    )
    return GlobalScalacPlugins(loaded_global_plugins.names, classpath)


def rules():
    return (
        *collect_rules(),
        *jvm_tool_rules(),
        UnionRule(JvmToolLockfileSentinel, GlobalScalacPluginsToolLockfileSentinel),
    )
