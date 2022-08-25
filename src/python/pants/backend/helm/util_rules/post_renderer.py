# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.docker.goals.package_image import DockerFieldSet
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules import (
    docker_binary,
    docker_build_args,
    docker_build_context,
    docker_build_env,
    dockerfile,
)
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.helm.dependency_inference.deployment import (
    FirstPartyHelmDeploymentMapping,
    FirstPartyHelmDeploymentMappingRequest,
)
from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.post_renderer import HelmPostRenderer, SetupHelmPostRenderer
from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.engine.addresses import Address, Addresses
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Targets
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HelmDeploymentPostRendererRequest(EngineAwareParameter):
    field_set: HelmDeploymentFieldSet

    def debug_hint(self) -> str | None:
        return self.field_set.address.spec


@rule(desc="Prepare Helm deployment post-renderer", level=LogLevel.DEBUG)
async def prepare_post_renderer_for_helm_deployment(
    request: HelmDeploymentPostRendererRequest,
    docker_options: DockerOptions,
) -> HelmPostRenderer:
    mapping = await Get(
        FirstPartyHelmDeploymentMapping, FirstPartyHelmDeploymentMappingRequest(request.field_set)
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
    docker_contexts = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=addr,
                build_upstream_images=False,
            ),
        )
        for addr in docker_addresses
    )

    docker_targets = await Get(Targets, Addresses(docker_addresses))
    field_sets = [DockerFieldSet.create(tgt) for tgt in docker_targets]

    def resolve_docker_image_ref(address: Address, context: DockerBuildContext) -> str | None:
        docker_field_sets = [fs for fs in field_sets if fs.address == address]
        if not docker_field_sets:
            return None

        docker_field_set = docker_field_sets[0]
        image_refs = docker_field_set.image_refs(
            default_repository=docker_options.default_repository,
            registries=docker_options.registries(),
            interpolation_context=context.interpolation_context,
        )

        # Choose first non-latest image reference found, or fallback to 'latest'.
        found_ref: str | None = None
        fallback_ref: str | None = None
        for ref in image_refs:
            if ref.endswith(":latest"):
                fallback_ref = ref
            else:
                found_ref = ref
                break

        resolved_ref = found_ref or fallback_ref
        if resolved_ref:
            logger.debug(f"Resolved Docker image ref '{resolved_ref}' for address {address}.")
        else:
            logger.warning(f"Could not resolve a valid image ref for Docker target {address}.")

        return resolved_ref

    docker_addr_ref_mapping = {
        addr: resolve_docker_image_ref(addr, ctx)
        for addr, ctx in zip(docker_addresses, docker_contexts)
    }

    def find_replacement(value: tuple[str, Address]) -> str | None:
        _, addr = value
        return docker_addr_ref_mapping.get(addr)

    replacements = mapping.indexed_docker_addresses.transform_values(find_replacement)

    return await Get(
        HelmPostRenderer,
        SetupHelmPostRenderer(replacements, description_of_origin=request.field_set.address.spec),
    )


def rules():
    return [
        *collect_rules(),
        *docker_binary.rules(),
        *docker_build_args.rules(),
        *docker_build_context.rules(),
        *docker_build_env.rules(),
        *dockerfile.rules(),
        *dockerfile_parser.rules(),
        *post_renderer.rules(),
    ]
