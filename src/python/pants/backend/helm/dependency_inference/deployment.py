# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from pants.backend.docker.target_types import AllDockerImageTargets
from pants.backend.docker.target_types import rules as docker_target_types_rules
from pants.backend.helm.dependency_inference.subsystem import (
    HelmInferSubsystem,
    UnownedDependencyError,
    UnownedDependencyUsage,
)
from pants.backend.helm.subsystems import k8s_parser
from pants.backend.helm.subsystems.k8s_parser import ParsedKubeManifest, ParseKubeManifestRequest
from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.backend.helm.target_types import rules as helm_target_types_rules
from pants.backend.helm.util_rules import renderer
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    RenderedHelmFiles,
)
from pants.backend.helm.utils.yaml import FrozenYamlIndex, MutableYamlIndex
from pants.build_graph.address import MaybeAddress
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import Digest, DigestEntries, FileEntry
from pants.engine.internals.native_engine import AddressInput, AddressParseException
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyseHelmDeploymentRequest(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec


@dataclass(frozen=True)
class HelmDeploymentReport(EngineAwareReturnType):
    address: Address
    image_refs: FrozenYamlIndex[str]

    @property
    def all_image_refs(self) -> FrozenOrderedSet[str]:
        return FrozenOrderedSet(self.image_refs.values())

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def metadata(self) -> dict[str, Any] | None:
        return {"address": self.address, "image_refs": self.image_refs}


@rule(desc="Analyse Helm deployment", level=LogLevel.DEBUG)
async def analyse_deployment(request: AnalyseHelmDeploymentRequest) -> HelmDeploymentReport:
    rendered_deployment = await Get(
        RenderedHelmFiles,
        HelmDeploymentRequest(
            cmd=HelmDeploymentCmd.RENDER,
            field_set=request.field_set,
            description=f"Rendering Helm deployment {request.field_set.address}",
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

    # Build YAML index of Docker image refs for future processing during dependency inference or post-rendering.
    image_refs_index: MutableYamlIndex[str] = MutableYamlIndex()
    for manifest in parsed_manifests:
        for entry in manifest.found_image_refs:
            image_refs_index.insert(
                file_path=PurePath(manifest.filename),
                document_index=entry.document_index,
                yaml_path=entry.path,
                item=entry.unparsed_image_ref,
            )

    return HelmDeploymentReport(
        address=request.field_set.address, image_refs=image_refs_index.frozen()
    )


@dataclass(frozen=True)
class FirstPartyHelmDeploymentMappingRequest(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec


@dataclass(frozen=True)
class FirstPartyHelmDeploymentMapping:
    """A mapping between `helm_deployment` target addresses and tuples made up of a Docker image
    reference and a `docker_image` target address.

    The tuples of Docker image references and addresses are stored in a YAML index so we can track
    the locations in which the Docker image refs appear in the deployment files.
    """

    address: Address
    indexed_docker_addresses: FrozenYamlIndex[tuple[str, Address]]


@rule
async def first_party_helm_deployment_mapping(
    request: FirstPartyHelmDeploymentMappingRequest,
    docker_targets: AllDockerImageTargets,
    helm_infer: HelmInferSubsystem,
) -> FirstPartyHelmDeploymentMapping:
    deployment_report = await Get(
        HelmDeploymentReport, AnalyseHelmDeploymentRequest(request.field_set)
    )

    def image_ref_to_address_input(image_ref: str) -> tuple[str, AddressInput] | None:
        try:
            return image_ref, AddressInput.parse(
                image_ref,
                description_of_origin=f"the helm_deployment at {request.field_set.address}",
                relative_to=request.field_set.address.spec_path,
            )
        except AddressParseException:
            return None

    indexed_address_inputs = deployment_report.image_refs.transform_values(
        image_ref_to_address_input
    )
    maybe_addresses = await MultiGet(
        Get(MaybeAddress, AddressInput, ai) for _, ai in indexed_address_inputs.values()
    )

    docker_target_addresses = {tgt.address for tgt in docker_targets}
    maybe_addresses_by_ref = {
        ref: maybe_addr
        for ((ref, _), maybe_addr) in zip(indexed_address_inputs.values(), maybe_addresses)
    }

    def image_ref_to_actual_address(
        image_ref_ai: tuple[str, AddressInput]
    ) -> tuple[str, Address] | None:
        image_ref, _ = image_ref_ai
        maybe_addr = maybe_addresses_by_ref.get(image_ref)
        if not maybe_addr:
            return None
        if not isinstance(maybe_addr.val, Address):
            return None
        if maybe_addr.val not in docker_target_addresses:
            _handle_missing_docker_image(helm_infer, image_ref, maybe_addr)
            return None
        return image_ref, maybe_addr.val

    return FirstPartyHelmDeploymentMapping(
        address=request.field_set.address,
        indexed_docker_addresses=indexed_address_inputs.transform_values(
            image_ref_to_actual_address
        ),
    )


def _handle_missing_docker_image(
    helm_infer: HelmInferSubsystem, image_ref: str, maybe_addr: MaybeAddress
):
    message = f"Error resolving Docker image dependency of a Helm chart. `{image_ref}` was supplied but the docker target at `{maybe_addr.val}` does not exist."
    if helm_infer.unowned_dependency_behavior == UnownedDependencyUsage.RaiseError:
        raise UnownedDependencyError(message)
    elif helm_infer.unowned_dependency_behavior == UnownedDependencyUsage.LogWarning:
        logging.warning(message)
    else:
        return


class InferHelmDeploymentDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmDeploymentFieldSet


@rule(desc="Find the dependencies needed by a Helm deployment")
async def inject_deployment_dependencies(
    request: InferHelmDeploymentDependenciesRequest,
) -> InferredDependencies:
    chart_address, explicitly_provided_deps, mapping = await MultiGet(
        Get(Address, AddressInput, request.field_set.chart.to_address_input()),
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(
            FirstPartyHelmDeploymentMapping,
            FirstPartyHelmDeploymentMappingRequest(request.field_set),
        ),
    )

    dependencies: OrderedSet[Address] = OrderedSet()
    dependencies.add(chart_address)

    for imager_ref, candidate_address in mapping.indexed_docker_addresses.values():
        matches = frozenset([candidate_address]).difference(explicitly_provided_deps.includes)
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            matches,
            request.field_set.address,
            context=softwrap(
                f"""
                The Helm deployment {request.field_set.address} declares
                {imager_ref} as Docker image reference
                """
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
