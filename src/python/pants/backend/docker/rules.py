# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass

from pants.backend.docker.rules_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.rules_binary import rules as binary_rules
from pants.backend.docker.rules_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.rules_context import rules as context_rules
from pants.backend.docker.target_types import (
    DockerContextRoot,
    DockerImageSources,
    DockerImageVersion,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.fs import Digest, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerFieldSet(PackageFieldSet):
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
    docker = await Get(DockerBinary, DockerBinaryRequest())
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
        *context_rules(),
        *binary_rules(),
        UnionRule(PackageFieldSet, DockerFieldSet),
    ]
