# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import (
    ScalaConsumedPluginNamesField,
    ScalacPluginArtifactField,
    ScalacPluginNameField,
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
    AllTargets,
    CoarsenedTargets,
    FieldDefaults,
    Target,
    Targets,
    TargetTypesToGenerateTargetsRequests,
    WrappedTarget,
)
from pants.jvm.compile import ClasspathEntry, FallibleClasspathEntry
from pants.jvm.goals import lockfile
from pants.jvm.resolve.coursier_fetch import CoursierFetchRequest
from pants.jvm.resolve.jvm_tool import rules as jvm_tool_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list, softwrap


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
        plugins: OrderedSet[Target] = OrderedSet()
        artifacts: OrderedSet[Target] = OrderedSet()

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
async def resolve_scala_plugins_for_target(
    request: ScalaPluginsForTargetRequest,
    all_scala_plugins: AllScalaPluginTargets,
    jvm: JvmSubsystem,
    scalac: Scalac,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
    local_environment_name: ChosenLocalEnvironmentName,
    field_defaults: FieldDefaults,
) -> ScalaPluginTargetsForTarget:
    target = request.target
    resolve = request.resolve_name

    plugin_names = target.get(ScalaConsumedPluginNamesField).value
    if plugin_names is None:
        plugin_names_by_resolve = scalac.parsed_default_plugins()
        plugin_names = tuple(plugin_names_by_resolve.get(resolve, ()))

    candidate_plugins = []
    candidate_artifacts = []
    for plugin in all_scala_plugins:
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
    )
