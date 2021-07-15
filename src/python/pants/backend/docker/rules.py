# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Sources, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
    required_fields = (DockerImageSources,)

    docker_image_sources: DockerImageSources


@rule(level=LogLevel.DEBUG)
async def package_pex_binary(
    field_set: DockerFieldSet,
) -> BuiltPackage:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    all_sources = await Get(
        SourceFiles, SourceFilesRequest([t.get(Sources) for t in transitive_targets.closure])
    )
    dockerfile = field_set.docker_image_sources.path_globs(FilesNotFoundBehavior.error).globs[0]
    result = await Get(
        ProcessResult,
        Process(
            argv=("docker", "build", dockerfile),
            input_digest=all_sources.snapshot.digest,
            output_files=tuple(),
            description=f"Building docker image from {dockerfile}",
        ),
    )
    return BuiltPackage(result.output_digest, (BuiltPackageArtifact("DUMMY"),))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]
