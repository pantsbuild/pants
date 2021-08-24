# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.engine.fs import Digest
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    SearchPath,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel


class DockerBinary(BinaryPath):
    """The `docker` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))

    def build_image(
        self, tag: str, digest: Digest, context_root: str, dockerfile: Optional[str] = None
    ) -> Process:
        args = [self.path, "build", "-t", tag]
        if dockerfile:
            args.extend(["-f", dockerfile])
        args.append(context_root)

        return Process(
            argv=tuple(args),
            input_digest=digest,
            description=f"Building docker image {tag}",
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
        raise BinaryNotFoundError(request, rationale="interact with the docker daemon")
    return DockerBinary(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
