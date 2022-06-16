# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.docker.target_types import AllDockerImageTargets
from pants.backend.docker.target_types import rules as docker_target_types_rules
from pants.backend.helm.target_types import (
    AllHelmDeploymentTargets,
    HelmDeploymentDependenciesField,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.target_types import rules as helm_target_types_rules
from pants.backend.helm.util_rules import deployment
from pants.backend.helm.util_rules import manifest as k8s_manifest
from pants.backend.helm.util_rules.deployment import RenderedDeployment, RenderHelmDeploymentRequest
from pants.backend.helm.util_rules.manifest import ImageRef, KubeManifests, ParseKubeManifests
from pants.backend.helm.util_rules.yaml_utils import YamlElements
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyseHelmDeploymentRequest:
    field_set: HelmDeploymentFieldSet


@dataclass(frozen=True)
class HelmDeploymentReport:
    image_refs: YamlElements[ImageRef]

    @property
    def all_image_refs(self) -> FrozenOrderedSet[ImageRef]:
        return FrozenOrderedSet(self.image_refs.values())


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
        image_refs=YamlElements(
            {
                manifest.filename: {
                    container.element_path / "image": container.image
                    for container in manifest.all_containers
                }
                for manifest in manifests
                if manifest.pod_spec
            }
        )
    )


@dataclass(frozen=True)
class FirstPartyHelmDeploymentMappings:
    docker_images: FrozenDict[Address, YamlElements[Address]]

    def referenced_by(self, address: Address) -> list[Address]:
        if address not in self.docker_images:
            return []
        return list(self.docker_images[address].values())


@rule
async def first_party_helm_deployment_mappings(
    deployment_targets: AllHelmDeploymentTargets, docker_targets: AllDockerImageTargets
) -> FirstPartyHelmDeploymentMappings:
    field_sets = [HelmDeploymentFieldSet.create(tgt) for tgt in deployment_targets]
    all_deployments_info = await MultiGet(
        Get(HelmDeploymentReport, AnalyseHelmDeploymentRequest(field_set))
        for field_set in field_sets
    )

    def image_refs_to_addresses(info: HelmDeploymentReport) -> YamlElements[Address]:
        """Filters the `ImageRef`s that are in fact `docker_image` addresses and returns those."""

        return YamlElements(
            {
                filename: {
                    elem_path: tgt.address
                    for tgt in docker_targets
                    for elem_path, ref in info.image_refs.yaml_items(filename)
                    if str(ref) == str(tgt.address)
                }
                for filename in info.image_refs.file_paths()
            }
        )

    docker_images_mapping = {
        fs.address: image_refs_to_addresses(info)
        for fs, info in zip(field_sets, all_deployments_info)
    }
    return FirstPartyHelmDeploymentMappings(docker_images=FrozenDict(docker_images_mapping))


class InjectHelmDeploymentDependenciesRequest(InjectDependenciesRequest):
    inject_for = HelmDeploymentDependenciesField


@rule(desc="Find the dependencies needed by a Helm deployment", level=LogLevel.DEBUG)
async def inject_deployment_dependencies(
    request: InjectHelmDeploymentDependenciesRequest, mapping: FirstPartyHelmDeploymentMappings
) -> InjectedDependencies:
    docker_images = mapping.referenced_by(request.dependencies_field.address)

    logging.debug(
        f"Found {pluralize(len(docker_images), 'dependency')} for target {request.dependencies_field.address}"
    )

    return InjectedDependencies(Addresses(docker_images))


def rules():
    return [
        *collect_rules(),
        *deployment.rules(),
        *k8s_manifest.rules(),
        *helm_target_types_rules(),
        *docker_target_types_rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmDeploymentDependenciesRequest),
    ]
