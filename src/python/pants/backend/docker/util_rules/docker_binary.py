# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.engine.fs import Digest
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessCacheScope,
    SearchPath,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class DockerBinary(BinaryPath):
    """The `docker` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))

    def build_image(
        self,
        tags: tuple[str, ...],
        digest: Digest,
        dockerfile: str | None = None,
        build_args: DockerBuildArgs | None = None,
        env: Mapping[str, str] | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> Process:
        args = [self.path, "build", *extra_args]

        for tag in tags:
            args.extend(["-t", tag])

        if build_args:
            for build_arg in build_args:
                args.extend(["--build-arg", build_arg])

        if dockerfile:
            args.extend(["-f", dockerfile])

        # Add build context root.
        args.append(".")

        return Process(
            argv=tuple(args),
            description=(
                f"Building docker image {tags[0]}"
                + (f" +{pluralize(len(tags)-1, 'additional tag')}." if len(tags) > 1 else "")
            ),
            env=env,
            input_digest=digest,
            cache_scope=ProcessCacheScope.PER_SESSION,
        )

    def push_image(
        self, tags: tuple[str, ...], env: Mapping[str, str] | None = None
    ) -> tuple[Process, ...]:
        return tuple(
            Process(
                argv=(self.path, "push", tag),
                cache_scope=ProcessCacheScope.PER_SESSION,
                description=f"Pushing docker image {tag}",
                env=env,
            )
            for tag in tags
        )

    def run_image(
        self,
        tag: str,
        *,
        docker_run_args: tuple[str, ...] | None = None,
        image_args: tuple[str, ...] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        return Process(
            argv=(self.path, "run", *(docker_run_args or []), tag, *(image_args or [])),
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Running docker image {tag}",
            env=env,
        )


@dataclass(frozen=True)
class DockerBinaryRequest:
    search_path: SearchPath = DockerBinary.DEFAULT_SEARCH_PATH


@rule(desc="Finding the `docker` binary", level=LogLevel.DEBUG)
async def find_docker(docker_request: DockerBinaryRequest) -> DockerBinary:
    request = BinaryPathRequest(
        binary_name="docker",
        search_path=docker_request.search_path,
        test=BinaryPathTest(args=["-v"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError.from_request(request, rationale="interact with the docker daemon")
    return DockerBinary(first_path.path, first_path.fingerprint)


@rule
async def get_docker() -> DockerBinary:
    return await Get(DockerBinary, DockerBinaryRequest())


def rules():
    return collect_rules()
