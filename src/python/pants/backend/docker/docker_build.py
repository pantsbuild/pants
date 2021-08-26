# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass

from pants.backend.docker.docker_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.docker_build_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.target_types import (
    DockerContextRoot,
    DockerImageSources,
    DockerImageVersion,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
    required_fields = (DockerImageSources,)

    context_root_field: DockerContextRoot
    image_version: DockerImageVersion
    sources: DockerImageSources

    @property
    def dockerfile_relpath(self) -> str:
        # DockerImageSources.expected_num_files==1 ensures this is non-empty
        assert self.sources.value
        return self.sources.value[0]

    @property
    def dockerfile_path(self) -> str:
        return os.path.join(self.address.spec_path, self.dockerfile_relpath)

    @property
    def context_root(self) -> str:
        """Translates context_root from a users perspective in the BUILD file, to Dockers
        perspective of the file system."""
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
    docker, context = await MultiGet(
        Get(DockerBinary, DockerBinaryRequest()),
        Get(
            DockerBuildContext, DockerBuildContextRequest(field_set.address, field_set.context_root)
        ),
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
                    "To push your image:",
                    f"    docker push {field_set.image_tag}",
                    "",
                ),
            ),
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]
