# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.docker.target_types import (
    DockerContextRoot,
    DockerImageSources,
    DockerImageVersion,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    DigestSubset,
    MergeDigests,
    PathGlobs,
    Snapshot,
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
    Sources,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


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

    packages_str = ", ".join(a.relpath for p in built_packages for a in p.artifacts if a.relpath)
    logger.debug(f"Packages for Docker image: {packages_str}")

    digest = await Get(Digest, MergeDigests(artifacts))

    return DockerPackages(artifacts=digest, built=built_packages)


# -----------------------------------------------------------------------------------------------
# Docker binary.
# -----------------------------------------------------------------------------------------------


class DockerBinary(BinaryPath):
    """The `docker` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))

    def build_image(
        self, tag: str, digest: Digest, context_root: str, dockerfile: Optional[str] = None
    ):
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
# Build Docker image.
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DockerBuildContext:
    digest: Digest


@dataclass(frozen=True)
class DockerBuildContextRequest:
    address: Address
    context_root: str
    targets: Tuple[Target, ...]


@rule
async def create_docker_build_context(request: DockerBuildContextRequest) -> DockerBuildContext:
    # Get all sources.
    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[t.get(Sources) for t in request.targets],
            for_sources_types=(DockerImageSources, FilesSources, ResourcesSources),
        ),
    )

    # Get all dependent targets.
    dependencies_targets = await MultiGet(
        Get(Targets, DependenciesRequest(t.get(Dependencies))) for t in request.targets
    )

    # Get all packages from those targets.
    dependencies_packages = await MultiGet(
        Get(DockerPackages, Targets, dep_targets) for dep_targets in dependencies_targets
    )

    packages_digest = tuple(
        package.artifacts for package in dependencies_packages if package.artifacts
    )
    if request.context_root != ".":
        # Copy packages to context root, unless the context root is at the project root
        packages_digest = await MultiGet(
            Get(Digest, AddPrefix(digest, request.context_root)) for digest in packages_digest
        )

    # Merge build context.
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
class DockerFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (DockerImageSources,)

    context_root_field: DockerContextRoot
    image_version: DockerImageVersion
    sources: DockerImageSources

    @property
    def dockerfile_name(self) -> str:
        if not self.sources.value:
            return "Dockerfile"
        return self.sources.value[0]

    @property
    def dockerfile_path(self) -> str:
        return os.path.join(self.address.spec_path, self.dockerfile_name)

    @property
    def context_root(self) -> str:
        path = self.context_root_field.value or "."
        if os.path.isabs(path):
            path = os.path.relpath(path, "/")
        else:
            path = os.path.join(self.address.spec_path, path)
        return path

    @property
    def image_tag(self) -> str:
        return ":".join(s for s in [self.address.target_name, self.image_version.value] if s)


@rule
async def build_docker_image(
    field_set: DockerFieldSet,
) -> BuiltPackage:
    docker = await Get(DockerBinary, DockerBinaryRequest(rationale="build docker images"))
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    context = await Get(
        DockerBuildContext,
        DockerBuildContextRequest(
            field_set.address, field_set.context_root, tuple(transitive_targets.closure)
        ),
    )

    snapshot = await Get(Snapshot, Digest, context.digest)
    files = "\n".join(snapshot.files)
    logger.debug(
        f"Docker build context [context_root: {field_set.context_root}] "
        f"for {field_set.image_tag!r}:\n"
        f"{files}"
    )

    result = await Get(
        ProcessResult,
        Process,
        docker.build_image(
            field_set.image_tag,
            context.digest,
            field_set.context_root,
            field_set.dockerfile_path,
        ),
    )

    logger.debug(
        f"Docker build output for {field_set.image_tag}:\n"
        f"{result.stdout.decode()}\n"
        f"{result.stderr.decode()}"
    )

    return BuiltPackage(
        result.output_digest,
        (
            BuiltPackageArtifact(
                relpath=None,
                extra_log_lines=(
                    f"Built docker image: {field_set.image_tag}",
                    "To try out the image interactively:",
                    f"    docker run -it --rm {field_set.image_tag} [entrypoint args...]",
                    "or using pants:",
                    f"    ./pants run {field_set.address} -- [entrypoint args...]",
                    "To push your image:",
                    f"    docker push {field_set.image_tag}",
                    "",
                ),
            ),
        ),
    )


@rule
async def create_docker_image_run_request(field_set: DockerFieldSet) -> RunRequest:
    docker = await Get(DockerBinary, DockerBinaryRequest(rationale="run docker images"))
    return RunRequest(
        digest=EMPTY_DIGEST,
        args=(
            docker.path,
            "run",
            "-it",
            "--rm",
            field_set.image_tag,
        ),
    )


# -----------------------------------------------------------------------------------------------
# Export Rules
# -----------------------------------------------------------------------------------------------


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
        UnionRule(RunFieldSet, DockerFieldSet),
    ]
