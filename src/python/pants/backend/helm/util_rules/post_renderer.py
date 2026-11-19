# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pants.backend.helm.dependency_inference.deployment import (
    FirstPartyHelmDeploymentMappingRequest,
    first_party_helm_deployment_mapping,
)
from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.post_renderer import SetupHelmPostRenderer
from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.backend.helm.util_rules import docker_image_ref
from pants.backend.helm.util_rules.docker_image_ref import (
    ResolveDockerImageRefRequest,
    resolve_docker_image_ref,
)
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmDeploymentPostRendererRequest(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec

    def metadata(self) -> dict[str, Any] | None:
        return {"address": self.field_set.address.spec}


@rule(desc="Prepare Helm deployment post-renderer", level=LogLevel.DEBUG)
async def prepare_post_renderer_for_helm_deployment(
    request: HelmDeploymentPostRendererRequest,
) -> SetupHelmPostRenderer:
    mapping = await first_party_helm_deployment_mapping(
        FirstPartyHelmDeploymentMappingRequest(request.field_set), **implicitly()
    )

    docker_addresses = [addr for _, addr in mapping.indexed_docker_addresses.values()]

    logger.debug(
        softwrap(
            f"""
            Resolving Docker image references for targets:

            {bullet_list([addr.spec for addr in docker_addresses])}
            """
        )
    )

    resolved_refs = await concurrently(
        resolve_docker_image_ref(ResolveDockerImageRefRequest(addr), **implicitly())
        for addr in docker_addresses
    )

    docker_addr_ref_mapping: dict[Address, str | None] = {}
    for addr, result in zip(docker_addresses, resolved_refs):
        if result.ref:
            logger.debug(f"Resolved Docker image ref '{result.ref}' for address {addr}.")
        else:
            logger.warning(f"Could not resolve a valid image ref for Docker target {addr}.")
        docker_addr_ref_mapping[addr] = result.ref

    def find_replacement(value: tuple[str, Address]) -> str | None:
        _, addr = value
        return docker_addr_ref_mapping.get(addr)

    replacements = mapping.indexed_docker_addresses.transform_values(find_replacement)

    return SetupHelmPostRenderer(
        replacements, description_of_origin=f"the `helm_deployment` {request.field_set.address}"
    )


def rules():
    return [
        *collect_rules(),
        *docker_image_ref.rules(),
        *post_renderer.rules(),
    ]
