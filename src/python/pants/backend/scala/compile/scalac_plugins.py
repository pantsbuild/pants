# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, cast

from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import (
    ScalaConsumedPluginNamesField,
    ScalacPluginArtifactField,
    ScalacPluginNameField,
    ScalacPluginTarget,
)
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import AllTargets, CoarsenedTargets, Target, Targets, WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry, FallibleClasspathEntry
from pants.jvm.goals import lockfile
from pants.jvm.resolve.coursier_fetch import (
    CoursierFetchRequest,
    ToolClasspath,
    ToolClasspathRequest,
)
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.resolve.jvm_tool import rules as jvm_tool_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import bullet_list


@dataclass(frozen=True)
class _LoadedGlobalScalacPlugins:
    names: tuple[str, ...]
    artifact_address_inputs: tuple[str, ...]


@dataclass(frozen=True)
class ScalaPluginsForTargetWithoutResolveRequest:
    target: Target


@dataclass(frozen=True)
class ScalaPluginsForTargetRequest:
    target: Target
    resolve_name: str


@dataclass(frozen=True)
class ScalaPluginTargetsForTarget:
    plugins: Targets
    artifacts: Targets


@dataclass(frozen=True)
class ScalaPluginsRequest:
    plugins: Targets
    artifacts: Targets
    resolve: CoursierResolveKey

    @classmethod
    def from_target_plugins(
        cls,
        seq: Iterable[ScalaPluginTargetsForTarget],
        resolve: CoursierResolveKey,
    ) -> ScalaPluginsRequest:
        plugins: set[Target] = set()
        artifacts: set[Target] = set()

        for spft in seq:
            plugins.update(spft.plugins)
            artifacts.update(spft.artifacts)

        return ScalaPluginsRequest(Targets(plugins), Targets(artifacts), resolve)


@dataclass(frozen=True)
class ScalaPlugins:
    names: tuple[str, ...]
    classpath: ClasspathEntry

    def args(self, prefix: str | None = None) -> Iterator[str]:
        p = f"{prefix}/" if prefix else ""
        for scalac_plugin_path in self.classpath.filenames:
            yield f"-Xplugin:{p}{scalac_plugin_path}"
        for name in self.names:
            yield f"-Xplugin-require:{name}"


class AllScalaPluginTargets(Targets):
    pass


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
            names.append(_plugin_name(target))
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


@rule
async def all_scala_plugin_targets(targets: AllTargets) -> AllScalaPluginTargets:
    return AllScalaPluginTargets(
        tgt for tgt in targets if tgt.has_fields((ScalacPluginArtifactField, ScalacPluginNameField))
    )


@rule
async def add_resolve_name_to_plugin_request(
    request: ScalaPluginsForTargetWithoutResolveRequest, jvm: JvmSubsystem
) -> ScalaPluginsForTargetRequest:
    return ScalaPluginsForTargetRequest(
        request.target, request.target[JvmResolveField].normalized_value(jvm)
    )


@rule
async def resolve_scala_plugins_for_target(
    request: ScalaPluginsForTargetRequest,
    all_scala_plugins: AllScalaPluginTargets,
    jvm: JvmSubsystem,
    scalac: Scalac,
) -> ScalaPluginTargetsForTarget:

    target = request.target
    resolve = request.resolve_name

    plugin_names = target.get(ScalaConsumedPluginNamesField).value
    if plugin_names is None:
        plugin_names_by_resolve = scalac.parsed_default_plugins()
        plugin_names = tuple(plugin_names_by_resolve.get(resolve, ()))

    candidate_plugins: list[Target] = []
    for plugin in all_scala_plugins:
        if _plugin_name(plugin) in plugin_names:
            candidate_plugins.append(plugin)

    artifact_address_inputs = (
        plugin[ScalacPluginArtifactField].value for plugin in candidate_plugins
    )

    artifact_addresses = await MultiGet(
        # `is not None` is solely to satiate mypy. artifact field is required.
        Get(Address, AddressInput, AddressInput.parse(ai))
        for ai in artifact_address_inputs
        if ai is not None
    )

    candidate_artifacts = await Get(Targets, Addresses(artifact_addresses))

    plugins: dict[str, tuple[Target, Target]] = {}  # Maps plugin name to relevant JVM artifact
    for plugin, artifact in zip(candidate_plugins, candidate_artifacts):
        if artifact[JvmResolveField].normalized_value(jvm) != resolve:
            continue

        plugins[_plugin_name(plugin)] = (plugin, artifact)

    for plugin_name in plugin_names:
        if plugin_name not in plugins:
            raise Exception(
                f"Could not find Scala plugin `{plugin_name}` in resolve `{resolve}` "
                f"for target {request.target}"
            )

    plugin_targets, artifact_targets = zip(*plugins.values()) if plugins else ((), ())
    return ScalaPluginTargetsForTarget(Targets(plugin_targets), Targets(artifact_targets))


def _plugin_name(target: Target) -> str:
    return target[ScalacPluginNameField].value or target.address.target_name


@rule
async def fetch_plugins(request: ScalaPluginsRequest) -> ScalaPlugins:
    # Fetch all the artifacts
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(target.address for target in request.artifacts)
    )
    fallible_artifacts = await MultiGet(
        Get(
            FallibleClasspathEntry,
            CoursierFetchRequest(ct, resolve=request.resolve),
        )
        for ct in coarsened_targets
    )

    artifacts = FallibleClasspathEntry.if_all_succeeded(fallible_artifacts)
    if artifacts is None:
        failed = [i for i in fallible_artifacts if i.exit_code != 0]
        raise Exception(f"Fetching local scala plugins failed: {failed}")

    merged_classpath_digest = await Get(Digest, MergeDigests(i.digest for i in artifacts))
    merged = ClasspathEntry.merge(merged_classpath_digest, artifacts)

    names = tuple(_plugin_name(target) for target in request.plugins)

    return ScalaPlugins(names=names, classpath=merged)


def rules():
    return (
        *collect_rules(),
        *jvm_tool_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, GlobalScalacPluginsToolLockfileSentinel),
    )
