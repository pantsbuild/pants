# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from typing import Iterable, Iterator, Mapping

from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import (
    AllScalacPluginTargets,
    ScalaConsumedPluginNamesField,
    ScalacPluginArtifactField,
    ScalacPluginFieldSet,
)
from pants.build_graph.address import Address, AddressInput
from pants.engine.addresses import Addresses
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.parametrize import (
    _TargetParametrizations,
    _TargetParametrizationsRequest,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    CoarsenedTarget,
    CoarsenedTargets,
    FieldDefaults,
    Target,
    Targets,
    TargetTypesToGenerateTargetsRequests,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, union
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
class InjectedScalacPlugin:
    name: str
    coordinate: Coordinate
    options: FrozenDict[str, str]

    def __init__(
        self, name: str, coordinate: Coordinate, *, options: Mapping[str, str] | None = None
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "coordinate", coordinate)
        object.__setattr__(self, "options", FrozenDict(options or {}))

    @property
    def scalac_options(self) -> frozenset[str]:
        return frozenset([f"-P:{self.name}:{opt}:{value}" for opt, value in self.options.items()])


@dataclass(frozen=True)
class InjectedScalacSettings:
    """A collection of globally injected scalac plugins and compiler options provided
    programatically by another subsystem.

    Other backends can provide with their own set of global plugins by implementing
    a rule like the following:

    class MyBackendScalacSettingsRequest(InjectedScalacSettingsRequest):
        pass

    @rule
    async def my_backend_scalac_plugins(_: MyBackendScalacSettingsRequest, ...) -> InjectedScalacSettings:
        return InjectedScalacSettings(
            subsystem="mysubsystem",
            plugins=[
                # List of plugins
                ...
            ],
            extra_scalac_options=[
                # Additional scalac options
                ...
            ]
        )

    def rules():
        return [
            *collect_rules(),
            UnionRule(InjectedScalacSettingsRequest, MyBackendScalacSettingsRequest)
        ]
    """

    subsystem: str
    plugins: tuple[InjectedScalacPlugin, ...]
    _extra_scalac_options: tuple[str, ...]

    def __init__(
        self,
        *,
        subsystem: str,
        plugins: Iterable[InjectedScalacPlugin] | None = None,
        extra_scalac_options: Iterable[str] | None = None,
    ) -> None:
        object.__setattr__(self, "subsystem", subsystem)
        object.__setattr__(self, "plugins", tuple(plugins or ()))
        object.__setattr__(self, "_extra_scalac_options", tuple(extra_scalac_options or ()))

    @property
    def plugin_names(self) -> frozenset[str]:
        return frozenset([plugin.name for plugin in self.plugins])

    @property
    def extra_scalac_options(self) -> frozenset[str]:
        return frozenset(
            [
                *self._extra_scalac_options,
                *chain.from_iterable(plugin.scalac_options for plugin in self.plugins),
            ]
        )


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class InjectScalacSettingsRequest:
    """A request to inject scalac settings and plugins for a given target."""

    target: Target
    resolve_name: str

    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return True


@dataclass(frozen=True)
class ScalacPluginsForTargetWithoutResolveRequest:
    target: Target


@dataclass(frozen=True)
class ScalacPluginsForTargetRequest:
    target: Target
    resolve_name: str


@dataclass(frozen=True)
class _LocalScalacPlugin:
    field_set: ScalacPluginFieldSet
    artifact: Target

    @property
    def name(self) -> str:
        return self.field_set.plugin_name

    @property
    def extra_scalac_options(self) -> tuple[str, ...]:
        plugin_options: Mapping[str, str] = dict(self.field_set.options.value or {})
        return tuple(
            [
                f"-P{self.field_set.plugin_name}:{name}:{value}"
                for name, value in plugin_options.items()
            ]
        )


@dataclass(frozen=True)
class _ConsumedScalacPlugins:
    plugins: tuple[_LocalScalacPlugin, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(plugin.name for plugin in self.plugins)

    @property
    def artifacts(self) -> Targets:
        return Targets([plugin.artifact for plugin in self.plugins])

    @property
    def extra_scalac_options(self) -> tuple[str, ...]:
        return tuple(chain.from_iterable(plugin.extra_scalac_options for plugin in self.plugins))


@dataclass(frozen=True)
class _InjectedScalacSettings:
    plugin_names: tuple[str, ...]
    plugin_artifacts: tuple[Target, ...]
    extra_scalac_options: tuple[str, ...]


@dataclass(frozen=True)
class ScalacPluginsForTarget:
    _injected_settings: _InjectedScalacSettings
    _consumed_plugins: _ConsumedScalacPlugins

    @property
    def names(self) -> tuple[str, ...]:
        return (*self._injected_settings.plugin_names, *self._consumed_plugins.names)

    @property
    def artifacts(self) -> Targets:
        return Targets(
            [*self._injected_settings.plugin_artifacts, *self._consumed_plugins.artifacts]
        )

    @property
    def extra_scalac_options(self) -> tuple[str, ...]:
        return (
            *self._injected_settings.extra_scalac_options,
            *self._consumed_plugins.extra_scalac_options,
        )


@dataclass(frozen=True)
class ScalacPluginsRequest:
    consumer_targets: tuple[Target, ...]
    resolve: CoursierResolveKey

    @classmethod
    def for_coarsened_target(
        cls, target: CoarsenedTarget, resolve: CoursierResolveKey
    ) -> ScalacPluginsRequest:
        return cls(consumer_targets=tuple(target.members), resolve=resolve)


@dataclass(frozen=True)
class ScalacPlugins:
    names: tuple[str, ...]
    classpath: ClasspathEntry
    extra_scalac_options: tuple[str, ...] = ()

    def __init__(
        self, names: Iterable[str], classpath: ClasspathEntry, extra_scalac_options: Iterable[str]
    ) -> None:
        object.__setattr__(self, "names", tuple(set(names)))
        object.__setattr__(self, "classpath", classpath)
        object.__setattr__(self, "extra_scalac_options", tuple(set(extra_scalac_options)))

    def args(self, prefix: str | None = None) -> Iterator[str]:
        p = f"{prefix}/" if prefix else ""
        for scalac_plugin_path in self.classpath.filenames:
            yield f"-Xplugin:{p}{scalac_plugin_path}"
        for name in self.names:
            yield f"-Xplugin-require:{name}"
        yield from self.extra_scalac_options


@rule
async def add_resolve_name_to_plugin_request(
    request: ScalacPluginsForTargetWithoutResolveRequest, jvm: JvmSubsystem
) -> ScalacPluginsForTargetRequest:
    return ScalacPluginsForTargetRequest(
        request.target, request.target[JvmResolveField].normalized_value(jvm)
    )


async def _find_scalac_plugin_artifact_target(
    field: ScalacPluginArtifactField,
    consumer_target: Target,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    local_environment_name: ChosenLocalEnvironmentName,
    field_defaults: FieldDefaults,
) -> WrappedTarget:
    """Helps finding the actual artifact for a scalac plugin even in the scenario in which the
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
                    Could not find a scalac plugin artifact {address} from target {field.address}
                    as it points to a target generator that produced more than one target:

                    {bullet_list([tgt.address.spec for tgt in generated_tgts])}
                    """
                )
            )
        if len(generated_tgts) == 1:
            target = generated_tgts[0]

    return WrappedTarget(target)


@rule
async def _resolve_local_scalac_plugins_for_target(
    request: ScalacPluginsForTargetRequest,
    all_scalac_plugin_targets: AllScalacPluginTargets,
    jvm: JvmSubsystem,
    scalac: Scalac,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    local_environment_name: ChosenLocalEnvironmentName,
    field_defaults: FieldDefaults,
) -> _ConsumedScalacPlugins:
    target = request.target
    resolve = request.resolve_name

    plugin_names = target.get(ScalaConsumedPluginNamesField).value
    if plugin_names is None:
        plugin_names_by_resolve = scalac.parsed_default_plugins()
        plugin_names = tuple(plugin_names_by_resolve.get(resolve, ()))

    candidate_plugin_fieldsets = []
    candidate_artifact_targets = []
    for plugin_tgt in all_scalac_plugin_targets:
        plugin_fs = ScalacPluginFieldSet.create(plugin_tgt)
        if plugin_fs.plugin_name not in plugin_names:
            continue

        candidate_plugin_fieldsets.append(plugin_fs)

        wrapped_target = await _find_scalac_plugin_artifact_target(
            plugin_fs.artifact,
            request.target,
            target_types_to_generate_requests,
            local_environment_name,
            field_defaults,
        )
        candidate_artifact_targets.append(wrapped_target.target)

    # Maps plugin name to relevant plugin field set and JVM artifact
    plugins: dict[str, _LocalScalacPlugin] = {}
    for plugin_fieldset, artifact_target in zip(
        candidate_plugin_fieldsets, candidate_artifact_targets
    ):
        if artifact_target[JvmResolveField].normalized_value(jvm) != resolve:
            continue

        plugins[plugin_fieldset.plugin_name] = _LocalScalacPlugin(plugin_fieldset, artifact_target)

    for plugin_name in plugin_names:
        if plugin_name not in plugins:
            raise Exception(
                f"Could not find Scala plugin `{plugin_name}` in resolve `{resolve}` "
                f"for target {request.target.address}."
            )

    return _ConsumedScalacPlugins(tuple(plugins.values()))


@rule
async def _resolve_global_scalac_plugins_for_target(
    request: ScalacPluginsForTargetRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    union_membership: UnionMembership,
    local_environment_name: ChosenLocalEnvironmentName,
) -> _InjectedScalacSettings:
    environment_name = local_environment_name.val

    all_injected_settings = await MultiGet(
        Get(
            InjectedScalacSettings,
            {
                request_type(request.target, request.resolve_name): InjectScalacSettingsRequest,
                environment_name: EnvironmentName,
            },
        )
        for request_type in union_membership.get(InjectScalacSettingsRequest)
        if request_type.is_applicable(request.target)
    )

    plugin_addresses: OrderedSet[Address] = OrderedSet()
    for injected_settings in all_injected_settings:
        found_addresses = find_jvm_artifacts_or_raise(
            required_coordinates=[plugin.coordinate for plugin in injected_settings.plugins],
            resolve=request.resolve_name,
            jvm_artifact_targets=jvm_artifact_targets,
            jvm=jvm,
            subsystem=injected_settings.subsystem,
            target_type=request.target.alias,
        )
        plugin_addresses.update(found_addresses)

    targets = await Get(Targets, Addresses(plugin_addresses))
    return _InjectedScalacSettings(
        plugin_names=tuple(
            chain.from_iterable(settings.plugin_names for settings in all_injected_settings)
        ),
        plugin_artifacts=tuple(targets),
        extra_scalac_options=tuple(
            chain.from_iterable(settings.extra_scalac_options for settings in all_injected_settings)
        ),
    )


@rule
async def resolve_all_scalac_plugins_for_target(
    request: ScalacPluginsForTargetRequest,
) -> ScalacPluginsForTarget:
    injected, consumed = await MultiGet(
        Get(_InjectedScalacSettings, ScalacPluginsForTargetRequest, request),
        Get(_ConsumedScalacPlugins, ScalacPluginsForTargetRequest, request),
    )
    return ScalacPluginsForTarget(injected, consumed)


@rule
async def fetch_plugins(request: ScalacPluginsRequest) -> ScalacPlugins:
    all_plugins = await MultiGet(
        Get(ScalacPluginsForTarget, ScalacPluginsForTargetRequest(tgt, request.resolve.name))
        for tgt in request.consumer_targets
    )

    # Fetch all the artifacts
    all_plugin_artifacts = set(chain.from_iterable([plugins.artifacts for plugins in all_plugins]))
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(target.address for target in all_plugin_artifacts)
    )
    fallible_classpath_entries = await MultiGet(
        Get(
            FallibleClasspathEntry,
            CoursierFetchRequest(ct, resolve=request.resolve),
        )
        for ct in coarsened_targets
    )

    classpath_entries = FallibleClasspathEntry.if_all_succeeded(fallible_classpath_entries)
    if classpath_entries is None:
        failed = [i for i in fallible_classpath_entries if i.exit_code != 0]
        raise Exception(f"Fetching scala plugins failed: {failed}")

    merged_classpath_digest = await Get(Digest, MergeDigests(i.digest for i in classpath_entries))
    merged = ClasspathEntry.merge(merged_classpath_digest, classpath_entries)

    return ScalacPlugins(
        names=chain.from_iterable([plugins.names for plugins in all_plugins]),
        classpath=merged,
        extra_scalac_options=chain.from_iterable(
            [plugins.extra_scalac_options for plugins in all_plugins]
        ),
    )


def rules():
    return (*collect_rules(), *jvm_tool_rules(), *lockfile.rules())
