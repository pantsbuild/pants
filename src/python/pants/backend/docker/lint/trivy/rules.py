# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any, cast

from pants.backend.docker.package_types import BuiltDockerImage
from pants.backend.docker.target_types import DockerImageSourceField, DockerImageTarget
from pants.backend.tools.trivy.rules import RunTrivyRequest, run_trivy
from pants.backend.tools.trivy.subsystem import SkipTrivyField, Trivy
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.goals.package import BuiltPackage, EnvironmentAwarePackageRequest, PackageFieldSet
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    Target,
    Targets,
)
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class TrivyDockerFieldSet(FieldSet):
    required_fields = (DockerImageSourceField,)

    source: DockerImageSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTrivyField).value


class TrivyDockerRequest(LintTargetsRequest):
    field_set_type = TrivyDockerFieldSet
    tool_subsystem = Trivy
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


def command_args():
    return (
        # workaround for Trivy DB being overloaded on pulls
        "--db-repository",
        "ghcr.io/aquasecurity/trivy-db,public.ecr.aws/aquasecurity/trivy-db",
        # quiet progress output, which just clutters logs
        "--no-progress",
    )


@rule(desc="Lint Docker image with Trivy", level=LogLevel.DEBUG)
async def run_trivy_docker(
    request: TrivyDockerRequest.Batch[TrivyDockerFieldSet, Any],
) -> LintResult:
    addrs = tuple(e.address for e in request.elements)
    tgts = await Get(Targets, Addresses(addrs))

    field_sets_per_tgt = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, tgts)
    )
    [field_set] = field_sets_per_tgt.field_sets

    package = await Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
    built_image: BuiltDockerImage = cast(BuiltDockerImage, package.artifacts[0])
    r = await run_trivy(
        RunTrivyRequest(
            command="image",
            command_args=command_args(),
            scanners=(),
            target=built_image.image_id,
            input_digest=EMPTY_DIGEST,
            description=f"Run Trivy on docker image {','.join(built_image.tags)}",
        ),
        **implicitly(),
    )

    return LintResult.create(request, r)


def rules():
    return (
        *collect_rules(),
        *TrivyDockerRequest.rules(),
        DockerImageTarget.register_plugin_field(SkipTrivyField),
    )
