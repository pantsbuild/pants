# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.docker.target_types import DockerImageSourceField
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.engine.addresses import Address
from pants.engine.fs import Digest
from pants.engine.internals.graph import hydrate_sources, resolve_target
from pants.engine.internals.native_engine import NativeDependenciesRequest
from pants.engine.intrinsics import parse_dockerfile_info
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import HydrateSourcesRequest, SourcesField, WrappedTargetRequest


class DockerfileInfoError(Exception):
    pass


@dataclass(frozen=True)
class DockerfileInfo:
    address: Address
    digest: Digest

    # Data from the parsed Dockerfile, keep in sync with
    # `dockerfile_wrapper_script.py:ParsedDockerfileInfo`:
    source: str
    build_args: DockerBuildArgs = DockerBuildArgs()
    copy_source_paths: tuple[str, ...] = ()
    copy_build_args: DockerBuildArgs = DockerBuildArgs()
    from_image_build_args: DockerBuildArgs = DockerBuildArgs()
    version_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DockerfileInfoRequest:
    address: Address


@rule
async def parse_dockerfile(request: DockerfileInfoRequest) -> DockerfileInfo:
    wrapped_target = await resolve_target(
        WrappedTargetRequest(request.address, description_of_origin="<infallible>"), **implicitly()
    )
    target = wrapped_target.target
    sources = await hydrate_sources(
        HydrateSourcesRequest(
            target.get(SourcesField),
            for_sources_types=(DockerImageSourceField,),
            enable_codegen=True,
        ),
        **implicitly(),
    )

    dockerfiles = sources.snapshot.files
    assert len(dockerfiles) == 1, (
        f"Internal error: Expected a single source file to Dockerfile parse request {request}, "
        f"got: {dockerfiles}."
    )

    try:
        results = await parse_dockerfile_info(NativeDependenciesRequest(sources.snapshot.digest))
        assert len(results.path_to_infos) == 1
        result = next(iter(results.path_to_infos.values()))
        return DockerfileInfo(
            address=target.address,
            digest=sources.snapshot.digest,
            source=result.source,
            build_args=DockerBuildArgs.from_strings(*result.build_args, duplicates_must_match=True),
            copy_source_paths=tuple(result.copy_source_paths),
            copy_build_args=DockerBuildArgs.from_strings(
                *result.copy_build_args, duplicates_must_match=True
            ),
            from_image_build_args=DockerBuildArgs.from_strings(
                *result.from_image_build_args, duplicates_must_match=True
            ),
            version_tags=tuple(result.version_tags),
        )
    except ValueError as e:
        raise DockerfileInfoError(
            f"Error while parsing {dockerfiles[0]} for the {request.address} target: {e}"
        ) from e


def rules():
    return collect_rules()
