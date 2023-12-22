# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from typing import Iterable, Iterator, Mapping

from pants.backend.scala.resolve.common import rules as scala_resolve_rules
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import (
    AllScalacPluginTargets,
    ScalaConsumedPluginNamesField,
    ScalacPluginArtifactField,
    ScalacPluginFieldSet,
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
from pants.util.strutil import bullet_list, softwrap


@dataclass(frozen=True)
class InjectedScalacPluginRequirement:
    name: str
    coordinate: Coordinate


@dataclass(frozen=True)
class InjectedScalacPlugin:
    subsystem: str
    requirement: InjectedScalacPluginRequirement | None
    extra_scalac_options: tuple[str, ...]

    def __init__(
        self,
        *,
        subsystem: str,
        requirement: InjectedScalacPluginRequirement | None = None,
        extra_scalac_options: Iterable[str] | None = None,
    ) -> None:
        object.__setattr__(self, "subsystem", subsystem)
        object.__setattr__(self, "requirement", requirement)
        object.__setattr__(self, "extra_scalac_options", tuple(extra_scalac_options or ()))


class InjectedScalacPlugins(Collection[InjectedScalacPlugin]):
    """A collection of globally injected scalac plugins provided programatically.

    Other backends can provide with their own set of global plugins by implementing
    a rule like the following:

    class MyBackendScalacPluginsRequest(InjectScalacPluginsRequest):
        pass

    @rule
    async def my_backend_scalac_plugins(_: MyBackendScalacPluginsRequest, ...) -> InjectedScalacPlugins:
        return InjectedScalacPlugins([
          # Custom list of plugins
        ])

    def rules():
        return [
            *collect_rules(),
            UnionRule(InjectScalacPluginsRequest, MyBackendScalacPluginsRequest)
        ]
    """


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class InjectScalacPluginsRequest:
    """A request to inject scalac plugins for a given target."""

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
class _LocalScalacPlugins:
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
class _GlobalScalacPlugins:
    names: tuple[str, ...]
    artifacts: tuple[Target, ...]
    extra_scalac_options: tuple[str, ...]


@dataclass(frozen=True)
class ScalacPluginsForTarget:
    _global: _GlobalScalacPlugins
    _local: _LocalScalacPlugins

    @property
    def names(self) -> tuple[str, ...]:
        return (*self._global.names, *self._local.names)

    @property
    def artifacts(self) -> Targets:
        return Targets([*self._global.artifacts, *self._local.artifacts])

    @property
    def extra_scalac_options(self) -> tuple[str, ...]:
        return (*self._global.extra_scalac_options, *self._local.extra_scalac_options)


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
) -> _LocalScalacPlugins:
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

    return _LocalScalacPlugins(tuple(plugins.values()))


@rule
async def _resolve_global_scalac_plugins_for_target(
    request: ScalacPluginsForTargetRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    union_membership: UnionMembership,
) -> _GlobalScalacPlugins:
    injected_plugins = InjectedScalacPlugins(
        chain.from_iterable(
            await MultiGet(
                Get(
                    InjectedScalacPlugins,
                    InjectScalacPluginsRequest,
                    request_type(request.target, request.resolve_name),
                )
                for request_type in union_membership.get(InjectScalacPluginsRequest)
                if request_type.is_applicable(request.target)
            )
        )
    )

    extra_scalac_options: set[str] = set()
    names_and_addresses = {}
    for plugin in injected_plugins:
        extra_scalac_options.update(plugin.extra_scalac_options)

        if not plugin.requirement:
            continue

        addresses = find_jvm_artifacts_or_raise(
            required_coordinates=[plugin.requirement.coordinate],
            resolve=request.resolve_name,
            jvm_artifact_targets=jvm_artifact_targets,
            jvm=jvm,
            subsystem=plugin.subsystem,
            target_type=request.target.alias,
        )
        assert len(addresses) == 1
        names_and_addresses[plugin.requirement.name] = list(addresses)[0]

    targets = await Get(Targets, Addresses(names_and_addresses.values()))

    return _GlobalScalacPlugins(
        names=tuple(names_and_addresses.keys()),
        artifacts=tuple(targets),
        extra_scalac_options=tuple(extra_scalac_options),
    )


@rule
async def merge_global_and_local_scalac_plugins(
    request: ScalacPluginsForTargetRequest,
) -> ScalacPluginsForTarget:
    global_plugins, local_plugins = await MultiGet(
        Get(_GlobalScalacPlugins, ScalacPluginsForTargetRequest, request),
        Get(_LocalScalacPlugins, ScalacPluginsForTargetRequest, request),
    )
    return ScalacPluginsForTarget(global_plugins, local_plugins)


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
    return (*collect_rules(), *jvm_tool_rules(), *lockfile.rules(), *scala_resolve_rules())
