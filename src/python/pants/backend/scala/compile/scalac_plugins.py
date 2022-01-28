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
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.goals import lockfile
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
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
            f"The `[{Scalac.options_scope}].plugins_global` option accepts only "
            f"`{ScalacPluginTarget.alias}` targets, but got:\n\n"
            f"{bullet_list(type(t).alias for t in invalid_targets)}"
        )

    return _LoadedGlobalScalacPlugins(
        names=tuple(names), artifact_address_inputs=tuple(artifact_address_inputs)
    )


class GlobalScalacPluginsToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = "scalac-plugins"


@rule
def generate_global_scalac_plugins_lockfile_request(
    _: GlobalScalacPluginsToolLockfileSentinel,
    loaded_global_plugins: _LoadedGlobalScalacPlugins,
    scalac: Scalac,
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool(
        FrozenOrderedSet(loaded_global_plugins.artifact_address_inputs),
        artifact_option_name=f"[{scalac.options_scope}].plugins_global",
        lockfile_option_name=f"[{scalac.options_scope}].plugins_global_lockfile",
        resolve_name="scalac-plugins",
        lockfile_dest=scalac.plugins_global_lockfile,
        default_lockfile_resource=scalac.default_plugins_lockfile_resource,
    )


@dataclass(frozen=True)
class GlobalScalacPlugins:
    names: tuple[str, ...]
    classpath: ToolClasspath

    def args(self, prefix: str | None = None) -> Iterator[str]:
        for scalac_plugin_path in self.classpath.classpath_entries(prefix):
            yield f"-Xplugin:{scalac_plugin_path}"
        for name in self.names:
            yield f"-Xplugin-require:{name}"


@rule
async def global_scalac_plugins(
    loaded_global_plugins: _LoadedGlobalScalacPlugins,
) -> GlobalScalacPlugins:
    lockfile_request = await Get(
        GenerateJvmLockfileFromTool, GlobalScalacPluginsToolLockfileSentinel()
    )
    classpath = await Get(
        ToolClasspath,
        ToolClasspathRequest(prefix="__scalac_plugin_cp", lockfile=lockfile_request),
    )
    return GlobalScalacPlugins(loaded_global_plugins.names, classpath)


def rules():
    return (
        *collect_rules(),
        *jvm_tool_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, GlobalScalacPluginsToolLockfileSentinel),
    )
