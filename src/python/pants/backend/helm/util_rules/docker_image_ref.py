# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.docker.goals.package_image import DockerPackageFieldSet
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import (
    DockerImageTags,
    DockerImageTagsRequest,
    get_docker_image_tags,
)
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
    create_docker_build_context,
)
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.graph import resolve_target
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import WrappedTargetRequest
from pants.engine.unions import UnionMembership
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolveDockerImageRefRequest(EngineAwareParameter):
    """Request to resolve a Docker image target address to its fully qualified image reference."""

    address: Address

    def debug_hint(self) -> str | None:
        return self.address.spec


@dataclass(frozen=True)
class ResolvedDockerImageRef:
    """The resolved Docker image reference string, or None if not resolvable."""

    ref: str | None


def _pick_image_ref(field_set: DockerPackageFieldSet, context: DockerBuildContext,
                    docker_options: DockerOptions,
                    additional_tags: tuple[str, ...] = ()) -> str | None:
    """Choose the best image reference: prefer non-latest, fall back to latest."""
    image_refs = field_set.image_refs(
        default_repository=docker_options.default_repository,
        registries=docker_options.registries(),
        interpolation_context=context.interpolation_context,
        additional_tags=additional_tags,
    )

    found_ref: str | None = None
    fallback_ref: str | None = None
    for registry in image_refs:
        for tag in registry.tags:
            ref = tag.full_name
            if ref.endswith(":latest"):
                fallback_ref = ref
            else:
                found_ref = ref
                break

    return found_ref or fallback_ref


@rule(desc="Resolve Docker image reference", level=LogLevel.DEBUG)
async def resolve_docker_image_ref(
    request: ResolveDockerImageRefRequest,
    docker_options: DockerOptions,
    union_membership: UnionMembership,
) -> ResolvedDockerImageRef:
    """Resolve a Docker image target address to its fully qualified image reference."""
    wrapped_target = await resolve_target(
        WrappedTargetRequest(request.address, description_of_origin="<infallible>"), **implicitly()
    )
    target = wrapped_target.target

    if not DockerPackageFieldSet.is_applicable(target):
        return ResolvedDockerImageRef(ref=None)

    context = await create_docker_build_context(
        DockerBuildContextRequest(address=request.address, build_upstream_images=False),
        **implicitly(),
    )

    field_set = DockerPackageFieldSet.create(target)

    # Obtain custom image tags from union members.
    image_tags_requests = union_membership.get(DockerImageTagsRequest)
    found_image_tags = await concurrently(
        get_docker_image_tags(
            **implicitly({req_cls(target): DockerImageTagsRequest})
        )
        for req_cls in image_tags_requests
        if req_cls.is_applicable(target)
    )
    additional_tags = tuple(DockerImageTags(chain.from_iterable(found_image_tags)))

    ref = _pick_image_ref(field_set, context, docker_options, additional_tags)
    return ResolvedDockerImageRef(ref=ref)


def rules():
    return [
        *collect_rules(),
        *docker_binary.rules(),
        *docker_build_args.rules(),
        *docker_build_context.rules(),
        *docker_build_env.rules(),
        *dockerfile.rules(),
        *dockerfile_parser.rules(),
    ]
