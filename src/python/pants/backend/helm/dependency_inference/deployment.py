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
from pants.backend.helm.util_rules import manifest as k8s_manifest
from pants.backend.helm.util_rules import renderer
from pants.backend.helm.util_rules.manifest import ImageRef, KubeManifests, ParseKubeManifests
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentRendererCmd,
    HelmDeploymentRendererRequest,
    RenderedFiles,
)
from pants.backend.helm.util_rules.yaml_utils import FrozenYamlIndex, MutableYamlIndex
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmDeploymentReport:
    address: Address
    image_refs: FrozenYamlIndex[ImageRef]

    @property
    def all_image_refs(self) -> FrozenOrderedSet[ImageRef]:
        return FrozenOrderedSet(self.image_refs.values())


@rule(desc="Analyse Helm deployment", level=LogLevel.DEBUG)
async def analyse_deployment(field_set: HelmDeploymentFieldSet) -> HelmDeploymentReport:
    output_dir = "__output"

    rendered_deployment = await Get(
        RenderedFiles,
        HelmDeploymentRendererRequest(
            cmd=HelmDeploymentRendererCmd.TEMPLATE,
            field_set=field_set,
            description=f"Rendering Helm deployment {field_set.address}",
            output_directory=output_dir,
        ),
    )

    manifests = await Get(
        KubeManifests,
        ParseKubeManifests(rendered_deployment.snapshot.digest, field_set.address.spec),
    )

    # Build YAML index of `ImageRef`s for future processing during depedendecy inference or post-rendering.
    image_refs_index: MutableYamlIndex[ImageRef] = MutableYamlIndex()
    for manifest in manifests:
        for container in manifest.all_containers:
            image_refs_index.insert(
                file_path=manifest.filename,
                document_index=manifest.document_index,
                yaml_path=container.element_path / "image",
                item=container.image,
            )

    return HelmDeploymentReport(address=field_set.address, image_refs=image_refs_index.frozen())


@dataclass(frozen=True)
class FirstPartyHelmDeploymentMappings:
    deployment_to_docker_addresses: FrozenDict[Address, FrozenYamlIndex[Address]]

    def referenced_by(self, address: Address) -> list[Address]:
        if address not in self.deployment_to_docker_addresses:
            return []
        return list(self.deployment_to_docker_addresses[address].values())


@rule
async def first_party_helm_deployment_mappings(
    deployment_targets: AllHelmDeploymentTargets, docker_targets: AllDockerImageTargets
) -> FirstPartyHelmDeploymentMappings:
    field_sets = [HelmDeploymentFieldSet.create(tgt) for tgt in deployment_targets]
    all_deployments_info = await MultiGet(
        Get(HelmDeploymentReport, HelmDeploymentFieldSet, field_set) for field_set in field_sets
    )

    docker_target_addresses = {tgt.address.spec: tgt.address for tgt in docker_targets}

    def image_refs_to_addresses(info: HelmDeploymentReport) -> FrozenYamlIndex[Address]:
        """Maps and filters the `ImageRef`s that are in fact `docker_image` addresses and returns a
        YAML index of those addresses."""

        return info.image_refs.transform_values(
            lambda image_ref: docker_target_addresses.get(str(image_ref), None)
        )

    # Builds a mapping between `helm_deployment` addresses and a YAML index of `docker_image` addresses.
    address_mapping = {
        fs.address: image_refs_to_addresses(info)
        for fs, info in zip(field_sets, all_deployments_info)
    }
    return FirstPartyHelmDeploymentMappings(
        deployment_to_docker_addresses=FrozenDict(address_mapping)
    )


class HelmDeploymentDependenciesInferenceFieldSet(FieldSet):
    required_fields = (HelmDeploymentDependenciesField,)

    dependencies = HelmDeploymentDependenciesField


class InferHelmDeploymentDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmDeploymentDependenciesInferenceFieldSet


@rule(desc="Find the dependencies needed by a Helm deployment", level=LogLevel.DEBUG)
async def inject_deployment_dependencies(
    request: InferHelmDeploymentDependenciesRequest, mapping: FirstPartyHelmDeploymentMappings
) -> InferredDependencies:
    docker_images = mapping.referenced_by(request.field_set.address)

    logging.debug(
        f"Found {pluralize(len(docker_images), 'dependency')} for target {request.field_set.address}"
    )

    return InferredDependencies(docker_images)


def rules():
    return [
        *collect_rules(),
        *renderer.rules(),
        *k8s_manifest.rules(),
        *helm_target_types_rules(),
        *docker_target_types_rules(),
        UnionRule(InferDependenciesRequest, InferHelmDeploymentDependenciesRequest),
    ]
