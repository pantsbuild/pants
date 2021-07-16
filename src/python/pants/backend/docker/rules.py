# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from os import path

from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessResult,
    SearchPath,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Sources, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# Docker binary
# -----------------------------------------------------------------------------------------------


class DockerBinary(BinaryPath):
    """The `docker` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))

    def build_image(self, digest: Digest, build_root: str, dockerfile: str):
        return Process(
            argv=(self.path, "build", "-f", dockerfile, build_root),
            input_digest=digest,
            description=f"Building docker image from {dockerfile}",
        )


@dataclass(frozen=True)
class DockerBinaryRequest:
    rationale: str
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
        raise BinaryNotFoundError(request, rationale=docker_request.rationale)
    return DockerBinary(first_path.path, first_path.fingerprint)


# -----------------------------------------------------------------------------------------------
# Build image
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
    required_fields = (DockerImageSources,)

    docker_image_sources: DockerImageSources


@rule(level=LogLevel.DEBUG)
async def build_docker_image(
    field_set: DockerFieldSet,
) -> BuiltPackage:
    docker = await Get(DockerBinary, DockerBinaryRequest(rationale="build docker images"))
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    all_sources = await Get(
        SourceFiles, SourceFilesRequest([t.get(Sources) for t in transitive_targets.closure])
    )
    dockerfile = field_set.docker_image_sources.path_globs(FilesNotFoundBehavior.error).globs[0]
    source_path = path.dirname(dockerfile)
    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(all_sources.snapshot.digest, source_path, dockerfile),
    )
    return BuiltPackage(
        result.output_digest,
        (
            BuiltPackageArtifact(
                relpath=None,
                extra_log_lines=(
                    *result.stdout.decode().split("\n"),
                    *result.stderr.decode().split("\n"),
                ),
            ),
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]
