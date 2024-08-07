# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageBuildArgsField
from pants.backend.docker.utils import KeyValueSequenceUtil
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target


class DockerBuildArgs(KeyValueSequenceUtil):
    """Collection of arguments to pass to a Docker build."""

    def nonempty(self) -> dict[str, str]:
        return {k: v for k, v in self.to_dict().items() if v}

    def with_overrides(self, overrides: DockerBuildArgs) -> DockerBuildArgs:
        """Override the values in this collection.

        Will not extend with keys in overrides which do not exist in this collection.
        """
        overrides_dict = overrides.to_dict()
        return DockerBuildArgs.from_dict(
            {k: overrides_dict.get(k, v) for k, v in self.to_dict().items()}
        )

    def extended(self, more: Union[DockerBuildArgs, list[str]]) -> DockerBuildArgs:
        """Create a new DockerBuildArgs out of this and a list of strs to add."""
        if isinstance(more, DockerBuildArgs):
            return DockerBuildArgs.from_strings(*self, *more)
        else:
            return DockerBuildArgs.from_strings(*self, *more)


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
