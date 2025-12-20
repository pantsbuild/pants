# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pants.backend.kotlin.subsystems.kotlinc import KotlincSubsystem
from pants.backend.kotlin.target_types import (
    KotlincConsumedPluginIdsField,
    KotlincPluginArgsField,
    KotlincPluginArtifactField,
    KotlincPluginIdField,
)
from pants.build_graph.address import AddressInput
from pants.engine.addresses import Addresses
from pants.engine.internals.build_files import resolve_address
from pants.engine.internals.graph import resolve_coarsened_targets as coarsened_targets_get
from pants.engine.internals.graph import resolve_targets
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import AllTargets, Target, Targets
from pants.jvm.compile import ClasspathEntry, FallibleClasspathEntry
from pants.jvm.goals import lockfile
from pants.jvm.resolve.coursier_fetch import CoursierFetchRequest, fetch_with_coursier
from pants.jvm.resolve.jvm_tool import rules as jvm_tool_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class KotlincPluginsForTargetWithoutResolveRequest:
    target: Target


@dataclass(frozen=True)
class KotlincPluginsForTargetRequest:
    target: Target
    resolve_name: str


@dataclass(frozen=True)
class KotlincPluginTargetsForTarget:
    plugins: Targets
    artifacts: Targets


@dataclass(frozen=True)
class KotlincPluginsRequest:
    plugins: Targets
    artifacts: Targets
    resolve: CoursierResolveKey

    @classmethod
    def from_target_plugins(
        cls,
        seq: Iterable[KotlincPluginTargetsForTarget],
        resolve: CoursierResolveKey,
    ) -> KotlincPluginsRequest:
        plugins: set[Target] = set()
        artifacts: set[Target] = set()

        for spft in seq:
            plugins.update(spft.plugins)
            artifacts.update(spft.artifacts)

        return KotlincPluginsRequest(Targets(plugins), Targets(artifacts), resolve)


@dataclass(frozen=True)
class KotlincPlugins:
    ids: tuple[str, ...]
    classpath: ClasspathEntry
    plugin_args: FrozenDict[str, tuple[str, ...]]

    def args(self, prefix: str | None = None) -> Iterator[str]:
        p = f"{prefix}/" if prefix else ""
        for kotlinc_plugin_path in self.classpath.filenames:
            yield f"-Xplugin={p}{kotlinc_plugin_path}"
        for id in self.ids:
            for arg in self.plugin_args.get(id, ()):
                yield "-P"
                yield f"plugin:{id}:{arg}"


class AllKotlincPluginTargets(Targets):
    pass


@rule
async def all_kotlinc_plugin_targets(targets: AllTargets) -> AllKotlincPluginTargets:
    return AllKotlincPluginTargets(
        tgt
        for tgt in targets
        if tgt.has_fields(
            (KotlincPluginArtifactField, KotlincPluginIdField, KotlincPluginArgsField)
        )
    )


@rule
async def add_resolve_name_to_plugin_request(
    request: KotlincPluginsForTargetWithoutResolveRequest, jvm: JvmSubsystem
) -> KotlincPluginsForTargetRequest:
    return KotlincPluginsForTargetRequest(
        request.target, request.target[JvmResolveField].normalized_value(jvm)
    )


@rule
async def resolve_kotlinc_plugins_for_target(
    request: KotlincPluginsForTargetRequest,
    all_kotlinc_plugins: AllKotlincPluginTargets,
    jvm: JvmSubsystem,
    kotlinc: KotlincSubsystem,
) -> KotlincPluginTargetsForTarget:
    target = request.target
    resolve = request.resolve_name

    plugin_ids = target.get(KotlincConsumedPluginIdsField).value
    if plugin_ids is None:
        plugin_names_by_resolve = kotlinc.parsed_default_plugins()
        plugin_ids = tuple(plugin_names_by_resolve.get(resolve, ()))

    candidate_plugins = []
    for plugin in all_kotlinc_plugins:
        if _plugin_id(plugin) not in plugin_ids:
            continue
        candidate_plugins.append(plugin)

    address_inputs: list[AddressInput] = [
        plugin[KotlincPluginArtifactField].to_address_input() for plugin in candidate_plugins
    ]
    artifact_addresses = await concurrently(
        resolve_address(**implicitly({address_input: AddressInput}))
        for address_input in address_inputs
    )
    candidate_artifacts = await resolve_targets(**implicitly(Addresses(artifact_addresses)))

    plugins: dict[str, tuple[Target, Target]] = {}  # Maps plugin ID to relevant JVM artifact
    for plugin, artifact in zip(candidate_plugins, candidate_artifacts):
        if artifact[JvmResolveField].normalized_value(jvm) != resolve:
            continue

        plugins[_plugin_id(plugin)] = (plugin, artifact)

    for plugin_id in plugin_ids:
        if plugin_id not in plugins:
            raise Exception(
                f"Could not find `kotlinc` plugin `{plugin_id}` in resolve `{resolve}` "
                f"for target {request.target}"
            )

    plugin_targets, artifact_targets = zip(*plugins.values()) if plugins else ((), ())
    return KotlincPluginTargetsForTarget(Targets(plugin_targets), Targets(artifact_targets))


def _plugin_id(target: Target) -> str:
    plugin_id = target[KotlincPluginIdField].value
    if not plugin_id:
        plugin_id = target.address.target_name
    return plugin_id


@rule
async def fetch_kotlinc_plugins(request: KotlincPluginsRequest) -> KotlincPlugins:
    # Fetch all the artifacts
    coarsened_targets = await coarsened_targets_get(
        **implicitly(Addresses(target.address for target in request.artifacts))
    )
    fallible_artifacts = await concurrently(
        fetch_with_coursier(CoursierFetchRequest(ct, resolve=request.resolve))
        for ct in coarsened_targets
    )

    artifacts = FallibleClasspathEntry.if_all_succeeded(fallible_artifacts)
    if artifacts is None:
        failed = [i for i in fallible_artifacts if i.exit_code != 0]
        raise Exception(f"Fetching local kotlinc plugins failed: {failed}")

    entries = list(ClasspathEntry.closure(artifacts))
    merged_classpath_digest = await merge_digests(MergeDigests(entry.digest for entry in entries))
    merged = ClasspathEntry.merge(merged_classpath_digest, entries)

    ids = tuple(_plugin_id(target) for target in request.plugins)

    plugin_args = FrozenDict(
        {
            _plugin_id(plugin): tuple(plugin[KotlincPluginArgsField].value or [])
            for plugin in request.plugins
        }
    )

    return KotlincPlugins(ids=ids, classpath=merged, plugin_args=plugin_args)


def rules():
    return (
        *collect_rules(),
        *jvm_tool_rules(),
        *lockfile.rules(),
    )
