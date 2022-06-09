# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageBuildArgsField
from pants.backend.docker.utils import KeyValueSequenceUtil
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target


class DockerBuildArgs(KeyValueSequenceUtil):
    pass


@dataclass(frozen=True)
class DockerBuildArgsRequest:
    target: Target


@rule
async def docker_build_args(
    request: DockerBuildArgsRequest, docker_options: DockerOptions
) -> DockerBuildArgs:
    return DockerBuildArgs.from_strings(
        *docker_options.build_args,
        *(request.target.get(DockerImageBuildArgsField).value or ()),
    )


def rules():
    return collect_rules()
