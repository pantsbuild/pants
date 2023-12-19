# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from typing import Iterable, Iterator, Mapping, Sequence, Type, cast

from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import (
    AllScalacPluginTargets,
    ScalaConsumedPluginNamesField,
    ScalacPluginArtifactField,
    ScalacPluginNameField,
)
from pants.build_graph.address import Address, AddressInput
from pants.engine.addresses import Addresses
from pants.engine.collection import Collection
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.parametrize import (
    _TargetParametrizations,
    _TargetParametrizationsRequest,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    FieldDefaults,
    Target,
    Targets,
    TargetTypesToGenerateTargetsRequests,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.jvm.compile import ClasspathEntry, FallibleClasspathEntry
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.goals import lockfile
from pants.jvm.resolve.common import Coordinate
from pants.jvm.resolve.coursier_fetch import CoursierFetchRequest
from pants.jvm.resolve.jvm_tool import rules as jvm_tool_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list, softwrap


@dataclass(frozen=True)
class GlobalScalacPlugin:
    name: str
    subsystem: str
    coordinate: Coordinate | None
    extra_scalac_options: tuple[str, ...]


class GlobalScalacPlugins(Collection[GlobalScalacPlugin]):
    """A collection of global scalac plugins provided programatically.

    Other backends can provide with their own set of global plugins by implementing
    a rule like the following:

    class MyBackendScalacPluginsRequest(GlobalScalacPluginsRequest):
        pass

    @rule
    async def my_backend_scalac_plugins(_: MyBackendScalacPluginsRequest, ...) -> GlobalScalacPlugins:
        return GlobalScalacPlugins([
          # Custom list of plugins
        ])

    def rules():
        return [
            *collect_rules(),
            UnionRule(GlobalScalacPluginsRequest, MyBackendScalacPluginsRequest)
        ]
    """


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class GlobalScalacPluginsRequest:
    resolve_name: str

    @classmethod
    def rules(cls) -> Iterable:
        yield UnionRule(GlobalScalacPluginsRequest, cls)


class _GlobalScalacPluginsByResolve(FrozenDict[str, GlobalScalacPlugins]):
    pass


@rule
async def map_global_scalac_plugins_to_resolve(
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    union_membership: UnionMembership,
    local_environment_name: ChosenLocalEnvironmentName,
) -> _GlobalScalacPluginsByResolve:
    all_resolves = sorted(jvm.resolves.keys())
    environment_name = local_environment_name.val

    requests_by_resolve = [
        (resolve, request_type)
        for resolve in all_resolves
        for request_type in union_membership.get(GlobalScalacPluginsRequest)
        if scala.is_scala_resolve(resolve)
    ]

    global_plugins = await MultiGet(
        Get(
            GlobalScalacPlugins,
            {marker_cls(resolve): GlobalScalacPluginsRequest, environment_name: EnvironmentName},
        )
        for resolve, marker_cls in requests_by_resolve
    )

    return _GlobalScalacPluginsByResolve(
        {resolve: plugins for (resolve, _), plugins in zip(requests_by_resolve, global_plugins)}
    )


@dataclass(frozen=True)
class ResolvedGlobalScalacPlugins:
    names: tuple[str, ...]
    artifacts: tuple[Target, ...]
    extra_scalac_options: tuple[str, ...]


class ResolveGlobalScalacPluginMapping(FrozenDict[str, ResolvedGlobalScalacPlugins]):
    """A map that links a given resolve with the set of global scalac plugins for that resolve."""


@rule(_masked_types=[EnvironmentName])
async def resolve_all_global_scalac_plugins(
    jvm: JvmSubsystem,
    jvm_artifact_targets: AllJvmArtifactTargets,
    global_plugins_mapping: _GlobalScalacPluginsByResolve,
) -> ResolveGlobalScalacPluginMapping:
    all_addresses: Mapping[str, set[Address]] = defaultdict(set)
    for resolve, plugins in global_plugins_mapping.items():
        for plugin in plugins:
            if not plugin.coordinate:
                continue

            addresses = find_jvm_artifacts_or_raise(
                required_coordinates=[plugin.coordinate],
                resolve=resolve,
                jvm_artifact_targets=jvm_artifact_targets,
                jvm=jvm,
                subsystem=plugin.subsystem,
                target_type="n/a",
            )
            all_addresses[resolve].update(addresses)

    all_resolves = sorted(jvm.resolves.keys())
    addresses_by_resolves = [(resolve, all_addresses[resolve]) for resolve in all_resolves]

    all_targets = await MultiGet(
        Get(Targets, Addresses(addrs)) for (_, addrs) in addresses_by_resolves
    )
    targets_by_resolve = {
        resolve: tgt for (resolve, _), tgt in zip(addresses_by_resolves, all_targets)
    }

    mapping: Mapping[str, ResolvedGlobalScalacPlugins] = {
        resolve: ResolvedGlobalScalacPlugins(
            names=tuple(
                plugin.name for plugin in global_plugins_mapping[resolve] if plugin.coordinate
            ),
            artifacts=tuple(targets_by_resolve.get(resolve)),
            extra_scalac_options=tuple(
                chain.from_iterable(
                    plugin.extra_scalac_options for plugin in global_plugins_mapping[resolve]
                )
            ),
        )
        for resolve in all_resolves
    }
    return ResolveGlobalScalacPluginMapping(mapping)


@dataclass(frozen=True)
class ScalacPluginsForTargetWithoutResolveRequest:
    target: Target


@dataclass(frozen=True)
class ScalacPluginsForTargetRequest:
    target: Target
    resolve_name: str


@dataclass(frozen=True)
class ScalacPluginTargetsForTarget:
    plugins: Targets
    artifacts: Targets


@dataclass(frozen=True)
class ScalacPluginsRequest:
    plugins: Targets
    artifacts: Targets
    resolve: CoursierResolveKey

    @classmethod
    def from_target_plugins(
        cls,
        seq: Iterable[ScalacPluginTargetsForTarget],
        resolve: CoursierResolveKey,
    ) -> ScalacPluginsRequest:
        plugins: OrderedSet[Target] = OrderedSet()
        artifacts: OrderedSet[Target] = OrderedSet()

        for spft in seq:
            plugins.update(spft.plugins)
            artifacts.update(spft.artifacts)

        return ScalacPluginsRequest(Targets(plugins), Targets(artifacts), resolve)


@dataclass(frozen=True)
class ScalacPlugins:
    names: tuple[str, ...]
    classpath: ClasspathEntry
    extra_scalac_options: tuple[str, ...] = ()

    def args(self, prefix: str | None = None) -> Iterator[str]:
        p = f"{prefix}/" if prefix else ""
        for scalac_plugin_path in self.classpath.filenames:
            yield f"-Xplugin:{p}{scalac_plugin_path}"
        for name in self.names:
            yield f"-Xplugin-require:{name}"
        for scalac_opt in self.extra_scalac_options:
            yield scalac_opt


@rule
async def add_resolve_name_to_plugin_request(
    request: ScalacPluginsForTargetWithoutResolveRequest, jvm: JvmSubsystem
) -> ScalacPluginsForTargetRequest:
    return ScalacPluginsForTargetRequest(
        request.target, request.target[JvmResolveField].normalized_value(jvm)
    )


async def _resolve_scalac_plugin_artifact(
    field: ScalacPluginArtifactField,
    consumer_target: Target,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    local_environment_name: ChosenLocalEnvironmentName,
    field_defaults: FieldDefaults,
) -> WrappedTarget:
    """Helps resolving the actual artifact for a scalac plugin even in the scenario in which the
    artifact has been declared as a scala_artifact and it has been parametrized (i.e. across
    multiple resolves for cross building)."""

    environment_name = local_environment_name.val

    address = await Get(Address, AddressInput, field.to_address_input())

    parametrizations = await Get(
        _TargetParametrizations,
        {
            _TargetParametrizationsRequest(
                address.maybe_convert_to_target_generator(),
                description_of_origin=(
                    f"the target generator {address.maybe_convert_to_target_generator()}"
                ),
            ): _TargetParametrizationsRequest,
            environment_name: EnvironmentName,
        },
    )

    target = parametrizations.get_subset(
        address, consumer_target, field_defaults, target_types_to_generate_requests
    )
    if (
        target_types_to_generate_requests.is_generator(target)
        and not target.address.is_generated_target
    ):
        generated_tgts = list(parametrizations.generated_for(target.address).values())
        if len(generated_tgts) > 1:
            raise Exception(
                softwrap(
                    f"""
                    Could not resolve scalac plugin artifact {address} from target {field.address}
                    as it points to a target generator that produced more than one target:

                    {bullet_list([tgt.address.spec for tgt in generated_tgts])}
                    """
                )
            )
        if len(generated_tgts) == 1:
            target = generated_tgts[0]

    return WrappedTarget(target)


@rule
async def resolve_scalac_plugins_for_target(
    request: ScalacPluginsForTargetRequest,
    all_scalac_plugins: AllScalacPluginTargets,
    jvm: JvmSubsystem,
    scalac: Scalac,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    local_environment_name: ChosenLocalEnvironmentName,
    field_defaults: FieldDefaults,
) -> ScalacPluginTargetsForTarget:
    target = request.target
    resolve = request.resolve_name

    plugin_names = target.get(ScalaConsumedPluginNamesField).value
    if plugin_names is None:
        plugin_names_by_resolve = scalac.parsed_default_plugins()
        plugin_names = tuple(plugin_names_by_resolve.get(resolve, ()))

    candidate_plugins = []
    candidate_artifacts = []
    for plugin in all_scalac_plugins:
        if _plugin_name(plugin) not in plugin_names:
            continue
        candidate_plugins.append(plugin)
        artifact_field = plugin[ScalacPluginArtifactField]
        wrapped_target = await _resolve_scalac_plugin_artifact(
            artifact_field,
            request.target,
            target_types_to_generate_requests,
            local_environment_name,
            field_defaults,
        )
        candidate_artifacts.append(wrapped_target.target)

    plugins: dict[str, tuple[Target, Target]] = {}  # Maps plugin name to relevant JVM artifact
    for plugin, artifact in zip(candidate_plugins, candidate_artifacts):
        if artifact[JvmResolveField].normalized_value(jvm) != resolve:
            continue

        plugins[_plugin_name(plugin)] = (plugin, artifact)

    for plugin_name in plugin_names:
        if plugin_name not in plugins:
            raise Exception(
                f"Could not find Scala plugin `{plugin_name}` in resolve `{resolve}` "
                f"for target {request.target.address}."
            )

    plugin_targets, artifact_targets = zip(*plugins.values()) if plugins else ((), ())
    return ScalacPluginTargetsForTarget(Targets(plugin_targets), Targets(artifact_targets))


def _plugin_name(target: Target) -> str:
    return target[ScalacPluginNameField].value or target.address.target_name


@rule
async def fetch_plugins(
    request: ScalacPluginsRequest, global_scalac_plugins: ResolveGlobalScalacPluginMapping
) -> ScalacPlugins:
    resolved_global_plugins = global_scalac_plugins.get(request.resolve.name)

    # Fetch all the artifacts
    all_plugin_artifacts = [
        *([tgt for tgt in resolved_global_plugins.artifacts] if resolved_global_plugins else []),
        *request.artifacts,
    ]
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(target.address for target in all_plugin_artifacts)
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

    names = tuple(
        [
            *([name for name in resolved_global_plugins.names] if resolved_global_plugins else []),
            *(_plugin_name(target) for target in request.plugins),
        ]
    )

    return ScalacPlugins(
        names=names,
        classpath=merged,
        extra_scalac_options=(
            resolved_global_plugins.extra_scalac_options if resolved_global_plugins else ()
        ),
    )


def rules():
    return (
        *collect_rules(),
        *jvm_tool_rules(),
        *lockfile.rules(),
    )
