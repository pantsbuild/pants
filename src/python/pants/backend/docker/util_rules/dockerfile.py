# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.docker.target_types import (
    DockerfileInstructionsField,
    DockerfileSourceField,
    DockerImageSourceField,
)
from pants.engine.fs import EMPTY_SNAPSHOT, CreateDigest, FileContent, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule


class GenerateDockerfileRequest(GenerateSourcesRequest):
    input = DockerfileSourceField
    output = DockerImageSourceField


@rule
async def generate_dockerfile(request: GenerateDockerfileRequest) -> GeneratedSources:
    instructions = request.protocol_target[DockerfileInstructionsField].value
    output = (
        await Get(
            Snapshot,
            CreateDigest(
                (
                    FileContent(
                        f"{request.protocol_target.residence_dir}/Dockerfile",
                        "\n".join([*instructions, ""]).encode(),
                    ),
                )
            ),
        )
        if instructions
        else EMPTY_SNAPSHOT
    )
    return GeneratedSources(output)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateDockerfileRequest),
    )
