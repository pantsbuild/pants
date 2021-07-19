# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from os import path
from typing import Optional, Tuple

from pants.backend.docker.target_types import (
    DockerContext,
    DockerDependencies,
    Dockerfile,
    DockerImageVersion,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    AddPrefix,
    Digest,
    DigestContents,
    DigestSubset,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
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
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    Sources,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerPackages:
    artifacts: Digest
    built: Tuple[BuiltPackage, ...]


# -----------------------------------------------------------------------------------------------
# Docker binary
# -----------------------------------------------------------------------------------------------


class DockerBinary(BinaryPath):
    """The `docker` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))

    def build_image(
        self, tag: str, digest: Digest, build_root: str, dockerfile: Optional[str] = None
    ):
        args = [self.path, "build", "-t", tag]
        if dockerfile:
            args.extend(["-f", dockerfile])
        args.append(build_root)

        return Process(
            argv=tuple(args),
            input_digest=digest,
            description=f"Building docker image {tag}",
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
    required_fields = (Dockerfile,)

    build_context: DockerContext
    dockerfile: Dockerfile
    image_version: DockerImageVersion
    dependencies: DockerDependencies


@rule(level=LogLevel.DEBUG)
async def build_docker_image(
    field_set: DockerFieldSet,
) -> BuiltPackage:
    dockerfile = field_set.dockerfile.value
    source_path = field_set.address.spec_path
    image_tag = ":".join(
        s for s in [field_set.address.target_name, field_set.image_version.value] if s
    )

    # get docker binary
    docker = await Get(DockerBinary, DockerBinaryRequest(rationale="build docker images"))

    # get source files
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    target_sources = await Get(
        SourceFiles, SourceFilesRequest([t.get(Sources) for t in transitive_targets.closure])
    )

    # get dockerfile
    dockerfile_digest = (
        await Get(
            Digest,
            PathGlobs(
                [dockerfile],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"{field_set.address}'s `{field_set.dockerfile.alias}` field",
            ),
        )
        if dockerfile
        else None
    )

    # get packages
    dep_targets = await Get(Targets, DependenciesRequest(field_set.dependencies))
    dep_packages = await Get(DockerPackages, Targets, dep_targets)
    packages_digest = await Get(Digest, AddPrefix(dep_packages.artifacts, source_path))

    # merge build context
    context = await Get(
        Digest,
        MergeDigests(
            d
            for d in (
                dockerfile_digest,
                target_sources.snapshot.digest,
                packages_digest,
            )
            if d
        ),
    )

    # run docker build
    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            image_tag,
            context,
            source_path,
            dockerfile,
        ),
    )

    return BuiltPackage(
        result.output_digest,
        (
            BuiltPackageArtifact(
                relpath=None,
                extra_log_lines=(
                    f"To try out the image interactively: docker run -it --rm {image_tag} [entrypoint args...]",
                ),
                #     *result.stdout.decode().split("\n"),
                #     *result.stderr.decode().split("\n"),
                # ),
            ),
        ),
    )


# -----------------------------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------------------------


@rule
async def get_packages(targets: Targets) -> DockerPackages:
    target_packages = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, targets)
    )
    built_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in target_packages.field_sets
    )

    artifacts = []

    for pkg in built_packages:
        artifacts.append(
            await Get(
                Digest,
                DigestSubset(
                    pkg.digest,
                    PathGlobs(artifact.relpath for artifact in pkg.artifacts if artifact.relpath),
                ),
            )
        )

    digest = await Get(Digest, MergeDigests(artifacts))
    return DockerPackages(artifacts=digest, built=built_packages)


class InjectDockerDependencies(InjectDependenciesRequest):
    inject_for = DockerDependencies


@rule
async def inject_docker_dependencies(request: InjectDockerDependencies) -> InjectedDependencies:
    """Inspects COPY instructions in the Dockerfile for references to known targets."""
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    dockerfile = original_tgt.target[Dockerfile]
    if not dockerfile.value:
        return InjectedDependencies()

    dockerfile_digest = await Get(
        Digest,
        PathGlobs(
            [dockerfile.value],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{original_tgt.target.address}'s `{dockerfile.alias}` field",
        ),
    )
    dockerfile_contents = await Get(DigestContents, Digest, dockerfile_digest)
    print(f"\n\nCONTENTS: {dockerfile_contents}\n\n")
    return InjectedDependencies()


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectDockerDependencies),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]
