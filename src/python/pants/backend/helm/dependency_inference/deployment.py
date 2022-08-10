# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.docker.target_types import AllDockerImageTargets
from pants.backend.docker.target_types import rules as docker_target_types_rules
from pants.backend.helm.subsystems import k8s_parser
from pants.backend.helm.subsystems.k8s_parser import ParsedKubeManifest, ParseKubeManifestRequest
from pants.backend.helm.target_types import (
    AllHelmDeploymentTargets,
    HelmDeploymentDependenciesField,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.target_types import rules as helm_target_types_rules
from pants.backend.helm.util_rules import renderer
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    RenderedHelmFiles,
)
from pants.backend.helm.utils.yaml import FrozenYamlIndex, MutableYamlIndex
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DigestEntries, FileEntry
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmDeploymentReport:
    address: Address
    image_refs: FrozenYamlIndex[str]

    @property
    def all_image_refs(self) -> FrozenOrderedSet[str]:
        return FrozenOrderedSet(self.image_refs.values())


@rule(desc="Analyse Helm deployment", level=LogLevel.DEBUG)
async def analyse_deployment(field_set: HelmDeploymentFieldSet) -> HelmDeploymentReport:
    rendered_deployment = await Get(
        RenderedHelmFiles,
        HelmDeploymentRequest(
            cmd=HelmDeploymentCmd.RENDER,
            field_set=field_set,
            description=f"Rendering Helm deployment {field_set.address}",
        ),
    )

    rendered_entries = await Get(DigestEntries, Digest, rendered_deployment.snapshot.digest)
    parsed_manifests = await MultiGet(
        Get(
            ParsedKubeManifest,
            ParseKubeManifestRequest(file=entry),
        )
        for entry in rendered_entries
        if isinstance(entry, FileEntry)
    )

    # Build YAML index of Docker image refs for future processing during depedendecy inference or post-rendering.
    image_refs_index: MutableYamlIndex[str] = MutableYamlIndex()
    for manifest in parsed_manifests:
        for (idx, path, image_ref) in manifest.found_image_refs:
            image_refs_index.insert(
                file_path=PurePath(manifest.filename),
                document_index=idx,
                yaml_path=path,
                item=image_ref,
            )

    return HelmDeploymentReport(address=field_set.address, image_refs=image_refs_index.frozen())


@dataclass(frozen=True)
class FirstPartyHelmDeploymentMappings:
    """A mapping between `helm_deployment` target addresses and tuples made up of a Docker image
    reference and a `docker_image` target address.

    The tuples of Docker image references and addresses are stored in a YAML index so we can track
    the locations in which the Docker image refs appear in the deployment files.
    """

    deployment_to_docker_addresses: FrozenDict[Address, FrozenYamlIndex[tuple[str, Address]]]

    def docker_addresses_referenced_by(self, address: Address) -> list[tuple[str, Address]]:
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

    def lookup_docker_addreses(image_ref: str) -> tuple[str, Address] | None:
        addr = docker_target_addresses.get(str(image_ref), None)
        if addr:
            return image_ref, addr
        return None

    # Builds a mapping between `helm_deployment` addresses and a YAML index of `docker_image` addresses.
    address_mapping = {
        fs.address: info.image_refs.transform_values(lookup_docker_addreses)
        for fs, info in zip(field_sets, all_deployments_info)
    }
    return FirstPartyHelmDeploymentMappings(
        deployment_to_docker_addresses=FrozenDict(address_mapping)
    )


@dataclass(frozen=True)
class HelmDeploymentDependenciesInferenceFieldSet(FieldSet):
    required_fields = (HelmDeploymentDependenciesField,)

    dependencies: HelmDeploymentDependenciesField


class InferHelmDeploymentDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmDeploymentDependenciesInferenceFieldSet


@rule(desc="Find the dependencies needed by a Helm deployment")
async def inject_deployment_dependencies(
    request: InferHelmDeploymentDependenciesRequest, mapping: FirstPartyHelmDeploymentMappings
) -> InferredDependencies:
    explicitly_provided_deps = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)
    )
    candidate_docker_addresses = mapping.docker_addresses_referenced_by(request.field_set.address)

    dependencies: OrderedSet[Address] = OrderedSet()
    for imager_ref, candidate_address in candidate_docker_addresses:
        matches = frozenset([candidate_address]).difference(explicitly_provided_deps.includes)
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            matches,
            request.field_set.address,
            context=softwrap(
                f"The Helm deployment {request.field_set.address} declares "
                f"{imager_ref} as Docker image reference"
            ),
            import_reference="manifest",
        )

        maybe_disambiguated = explicitly_provided_deps.disambiguated(matches)
        if maybe_disambiguated:
            dependencies.add(maybe_disambiguated)

    logging.debug(
        f"Found {pluralize(len(dependencies), 'dependency')} for target {request.field_set.address}"
    )
    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        *renderer.rules(),
        *k8s_parser.rules(),
        *helm_target_types_rules(),
        *docker_target_types_rules(),
        UnionRule(InferDependenciesRequest, InferHelmDeploymentDependenciesRequest),
    ]
