# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain
from typing import Generic, Iterable, TypeVar

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import AllDockerImageTargets
from pants.backend.docker.util_rules import (
    docker_build_args,
    docker_build_context,
    docker_build_env,
    dockerfile,
)
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.helm.target_types import (
    AllHelmDeploymentTargets,
    HelmDeploymentDependenciesField,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules import deployment
from pants.backend.helm.util_rules.deployment import RenderedDeployment, RenderHelmDeploymentRequest
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, WrappedTarget
from pants.engine.unions import UnionRule
from pants.k8s import manifest as k8s_manifest
from pants.k8s.manifest import ImageRef, KubeManifests, ParseKubeManifests
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyseHelmDeploymentRequest:
    field_set: HelmDeploymentFieldSet


T = TypeVar("T")


class HelmDeploymentPatch(Generic[T]):
    _locations: FrozenDict[str, FrozenDict[str, T]]


@dataclass(frozen=True)
class HelmDeploymentReport:
    image_refs: FrozenDict[str, FrozenOrderedSet[ImageRef]]

    @property
    def all_image_refs(self) -> FrozenOrderedSet[ImageRef]:
        return FrozenOrderedSet(chain.from_iterable(self.image_refs.values()))


@rule(desc="Analyse Helm deployment", level=LogLevel.DEBUG)
async def analyse_deployment(request: AnalyseHelmDeploymentRequest) -> HelmDeploymentReport:
    rendered_deployment = await Get(
        RenderedDeployment,
        RenderHelmDeploymentRequest(field_set=request.field_set),
    )

    manifests = await Get(
        KubeManifests,
        ParseKubeManifests(rendered_deployment.snapshot.digest, request.field_set.address.spec),
    )

    return HelmDeploymentReport(
        image_refs=FrozenDict(
            {
                manifest.filename: FrozenOrderedSet(manifest.container_images)
                for manifest in manifests
                if manifest.pod_spec
            }
        )
    )


@dataclass(frozen=True)
class FirstPartyHelmDeploymentMappings:
    docker_images: FrozenDict[Address, FrozenOrderedSet[Address]]


@rule
async def first_party_helm_deployment_mappings(
    deployment_targets: AllHelmDeploymentTargets, docker_targets: AllDockerImageTargets
) -> FirstPartyHelmDeploymentMappings:
    field_sets = [HelmDeploymentFieldSet.create(tgt) for tgt in deployment_targets]
    all_deployments_info = await MultiGet(
        Get(HelmDeploymentReport, AnalyseHelmDeploymentRequest(field_set))
        for field_set in field_sets
    )

    def image_refs_to_addresses(refs: Iterable[ImageRef]) -> FrozenOrderedSet[Address]:
        """Filters the `ImageRef`s that are in fact `docker_image` addresses and returns those."""
        return FrozenOrderedSet(
            [tgt.address for tgt in docker_targets for ref in refs if str(ref) == str(tgt.address)]
        )

    docker_images_mapping = {
        fs.address: image_refs_to_addresses(info.all_image_refs)
        for fs, info in zip(field_sets, all_deployments_info)
    }
    return FirstPartyHelmDeploymentMappings(docker_images=FrozenDict(docker_images_mapping))


@dataclass(frozen=True)
class HelmDeploymentContainerMapping:
    containers: FrozenDict[ImageRef, Address]


@rule
async def build_helm_deployment_mapping(
    all_targets: AllDockerImageTargets, docker_options: DockerOptions
) -> HelmDeploymentContainerMapping:
    docker_field_sets = [DockerFieldSet.create(tgt) for tgt in all_targets]
    docker_contexts = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=field_set.address,
                build_upstream_images=False,
            ),
        )
        for field_set in docker_field_sets
    )

    def parse_container_ref(
        field_set: DockerFieldSet, context: DockerBuildContext
    ) -> list[ImageRef]:
        image_refs = field_set.image_refs(
            default_repository=docker_options.default_repository,
            registries=docker_options.registries(),
            interpolation_context=context.interpolation_context,
        )
        return [ImageRef.parse(ref) for ref in image_refs]

    docker_image_refs = {
        container_ref: field_set.address
        for field_set, context in zip(docker_field_sets, docker_contexts)
        for container_ref in parse_container_ref(field_set, context)
    }
    return HelmDeploymentContainerMapping(containers=FrozenDict(docker_image_refs))


class InjectHelmDeploymentDependenciesRequest(InjectDependenciesRequest):
    inject_for = HelmDeploymentDependenciesField


@rule(desc="Find the dependencies needed by a Helm deployment", level=LogLevel.DEBUG)
async def inject_deployment_dependencies(
    request: InjectHelmDeploymentDependenciesRequest, mapping: HelmDeploymentContainerMapping
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    field_set = HelmDeploymentFieldSet.create(wrapped_target.target)
    report = await Get(HelmDeploymentReport, AnalyseHelmDeploymentRequest(field_set))

    logging.debug(
        f"Target {request.dependencies_field.address} references {pluralize(len(report.all_image_refs), 'image')}."
    )

    found_docker_image_addresses = [
        address
        for container_ref, address in mapping.containers.items()
        if container_ref in report.all_image_refs
    ]

    logging.debug(
        f"Found {pluralize(len(found_docker_image_addresses), 'dependency')} for target {request.dependencies_field.address}"
    )

    return InjectedDependencies(Addresses(found_docker_image_addresses))


def rules():
    return [
        *collect_rules(),
        *deployment.rules(),
        *k8s_manifest.rules(),
        *docker_build_context.rules(),
        *docker_build_args.rules(),
        *docker_build_env.rules(),
        *dockerfile.rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmDeploymentDependenciesRequest),
    ]
