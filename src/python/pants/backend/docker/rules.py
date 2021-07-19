# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.docker.dockerfile import Dockerfile
from pants.backend.docker.target_types import (
    DockerDependencies,
    DockerImageSources,
    DockerImageVersion,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address, Addresses
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
    Dependencies,
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    Sources,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnparsedAddressInputs,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# Dockerfile
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DockerfileRequest:
    """Request to parse Dockerfile."""

    sources: DockerImageSources


@dataclass(frozen=True)
class DockerfileDigest:
    """Parsed Dockerfile response."""

    digest: Digest
    dockerfile: Dockerfile


@rule
async def parse_dockerfile(request: DockerfileRequest) -> DockerfileDigest:
    dockerfile = request.sources.value[0]
    digest = (
        await Get(
            Digest,
            PathGlobs(
                [os.path.join(request.sources.address.spec_path, dockerfile)],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"{request.sources.address}'s `{request.sources.alias}` field",
            ),
        )
        if dockerfile
        else None
    )
    contents = await Get(DigestContents, Digest, digest) if digest else None

    source = contents[0].content.decode() if contents else ""
    logger.debug(f"Parse {dockerfile}:\n{source}")
    parsed = Dockerfile.parse(source)
    logger.debug(f"Result: {parsed}")

    return DockerfileDigest(digest=digest, dockerfile=parsed)


# -----------------------------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DockerPackages:
    artifacts: Optional[Digest] = None
    built: Tuple[BuiltPackage, ...] = tuple()


@rule
async def get_packages(targets: Targets) -> DockerPackages:
    if not targets:
        return DockerPackages()

    logger.debug(
        f"""Get packages for Docker image from: {", ".join(str(t.address) for t in targets)}"""
    )

    target_packages = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, targets)
    )
    built_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in target_packages.field_sets
    )

    if not built_packages:
        return DockerPackages()

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
    logger.debug(
        f"""Packages for Docker image: {", ".join(a.relpath for p in built_packages for a in p.artifacts)}"""
    )

    return DockerPackages(artifacts=digest, built=built_packages)


class InjectDockerDependencies(InjectDependenciesRequest):
    inject_for = DockerDependencies


@rule
async def inject_docker_dependencies(request: InjectDockerDependencies) -> InjectedDependencies:
    """Inspects COPY instructions in the Dockerfile for references to known targets."""
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    sources = original_tgt.target[DockerImageSources]
    if not sources.value:
        return InjectedDependencies()

    dockerfile_digest = await Get(DockerfileDigest, DockerfileRequest(sources))
    addresses = await Get(
        Addresses,
        UnparsedAddressInputs(
            list(dockerfile_digest.dockerfile.putative_target_addresses()),
            owning_address=original_tgt.target.address,
        ),
    )
    return InjectedDependencies(addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectDockerDependencies),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]


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
class DockerBuildContext:
    digest: Digest


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    source_path: str
    targets: Tuple[Target, ...]


@rule
async def create_docker_build_context(request: DockerBuildContextRequest) -> DockerBuildContext:
    # get all source files
    sources = await Get(SourceFiles, SourceFilesRequest([t.get(Sources) for t in request.targets]))

    # get all dependent targets
    dependencies_targets = await MultiGet(
        Get(Targets, DependenciesRequest(t.get(Dependencies))) for t in request.targets
    )

    # get all packages from those targets
    dependencies_packages = await MultiGet(
        Get(DockerPackages, Targets, dep_targets) for dep_targets in dependencies_targets
    )

    # copy packages to context root
    packages_digest = await MultiGet(
        Get(Digest, AddPrefix(package.artifacts, request.source_path))
        for package in dependencies_packages
        if package.artifacts
    )

    # merge build context
    context = await Get(
        Digest,
        MergeDigests(
            d
            for d in (
                sources.snapshot.digest,
                *packages_digest,
            )
            if d
        ),
    )
    return DockerBuildContext(context)


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
    required_fields = (DockerImageSources,)

    sources: DockerImageSources
    image_version: DockerImageVersion


@rule(level=LogLevel.DEBUG)
async def build_docker_image(
    field_set: DockerFieldSet,
) -> BuiltPackage:
    source_path = field_set.address.spec_path
    image_tag = ":".join(
        s for s in [field_set.address.target_name, field_set.image_version.value] if s
    )

    docker = await Get(DockerBinary, DockerBinaryRequest(rationale="build docker images"))
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    context = await Get(
        DockerBuildContext,
        DockerBuildContextRequest(field_set.address, source_path, transitive_targets.closure),
    )

    # run docker build
    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            image_tag,
            context.digest,
            source_path,
            os.path.join(source_path, field_set.sources.value[0]),
        ),
    )

    logger.debug(
        "Docker build output for {image_tag}:\n"
        f"{result.stdout.decode()}\n"
        f"{result.stderr.decode()}"
    )

    return BuiltPackage(
        result.output_digest,
        (
            BuiltPackageArtifact(
                relpath=None,
                extra_log_lines=(
                    f"Built docker image: {image_tag}",
                    f"To try out the image interactively: docker run -it --rm {image_tag} [entrypoint args...]",
                    f"To push your image: docker push {image_tag}",
                ),
            ),
        ),
    )
