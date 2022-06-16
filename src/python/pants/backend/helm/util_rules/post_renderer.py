# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
from pants.backend.helm.dependency_inference.deployment import FirstPartyHelmDeploymentMappings
from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.subsystems.post_renderer import (
    PostRendererLauncherSetup,
    SetupPostRendererLauncher,
)
from pants.backend.helm.target_types import HelmDeploymentFieldSet
from pants.backend.helm.util_rules.yaml_utils import YamlElements
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Targets


@dataclass(frozen=True)
class PreparePostRendererRequest:
    field_set: HelmDeploymentFieldSet


@rule
async def prepare_post_renderer(
    request: PreparePostRendererRequest,
    mappings: FirstPartyHelmDeploymentMappings,
    docker_options: DockerOptions,
) -> PostRendererLauncherSetup:
    docker_addresses = mappings.docker_images[request.field_set.address]
    docker_contexts = await MultiGet(
        Get(
            DockerBuildContext,
            DockerBuildContextRequest(
                address=addr,
                build_upstream_images=False,
            ),
        )
        for addr in docker_addresses.values()
    )

    docker_targets = await Get(Targets, Addresses(docker_addresses.values()))
    field_sets = [DockerFieldSet.create(tgt) for tgt in docker_targets]

    def resolve_docker_image_ref(address: Address, context: DockerBuildContext) -> str | None:
        docker_field_sets = [fs for fs in field_sets if fs.address == address]
        if not docker_field_sets:
            return None

        result = None
        docker_field_set = docker_field_sets[0]
        image_refs = docker_field_set.image_refs(
            default_repository=docker_options.default_repository,
            registries=docker_options.registries(),
            interpolation_context=context.interpolation_context,
        )
        if image_refs:
            result = image_refs[0]
        return result

    docker_addr_ref_mapping = {
        addr: resolve_docker_image_ref(addr, ctx)
        for addr, ctx in zip(docker_addresses.values(), docker_contexts)
    }
    replacements = YamlElements(
        {
            manifest: {
                path: str(docker_addr_ref_mapping[address])
                for path, address in docker_addresses.yaml_items(manifest)
                if docker_addr_ref_mapping[address]
            }
            for manifest in docker_addresses.file_paths()
        }
    )

    return await Get(PostRendererLauncherSetup, SetupPostRendererLauncher(replacements))


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
