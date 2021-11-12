# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.backend.docker.target_types import DockerImageInstructionsField, DockerImageSourceField
from pants.engine.fs import CreateDigest, FileContent, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, InvalidFieldException
from pants.engine.unions import UnionRule


class GenerateDockerfileRequest(GenerateSourcesRequest):
    # This will always run codegen when hydrating `docker_image`s, performing source validations but
    # does not generate anything if there are no `instructions` defined on the target.
    input = DockerImageSourceField
    output = DockerImageSourceField


@rule
async def hydrate_dockerfile(request: GenerateDockerfileRequest) -> GeneratedSources:
    target = request.protocol_target
    address = target.address
    instructions = target[DockerImageInstructionsField].value

    if instructions and request.protocol_sources.files:
        raise InvalidFieldException(
            f"The `{target.alias}` {address} provides both a Dockerfile with the `source` field, "
            "and Dockerfile contents with the `instructions` field, which is not supported.\n\n"
            "To fix, please either set `source=None` or `instructions=None`."
        )

    if not (instructions or request.protocol_sources.files):
        raise InvalidFieldException(
            f"The `{target.alias}` {address} does not specify any Dockerfile.\n\n"
            "Provide either the filename to a Dockerfile in your project workspace as the "
            "`source` field value, or the Dockerfile content to the `instructions` field."
        )

    def dockerfile_path():
        name_parts = ["Dockerfile", address.target_name, address.generated_name]
        return os.path.join(address.spec_path, ".".join(filter(bool, name_parts)))

    output = (
        await Get(
            Snapshot,
            CreateDigest(
                (FileContent(dockerfile_path(), "\n".join([*instructions, ""]).encode()),)
            ),
        )
        if instructions
        else request.protocol_sources
    )
    return GeneratedSources(output)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateDockerfileRequest),
    )
