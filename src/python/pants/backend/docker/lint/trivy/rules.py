# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageSourceField
from pants.backend.tools.trivy.rules import run_trivy, RunTrivyRequest
from pants.backend.tools.trivy.subsystem import Trivy, SkipTrivyField
from pants.core.goals.lint import LintTargetsRequest, LintResult
from pants.core.goals.package import EnvironmentAwarePackageRequest, PackageFieldSet, BuiltPackage
from pants.core.goals.test import BuiltPackageDependencies, BuildPackageDependenciesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import determine_source_files, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Digest, EMPTY_DIGEST, Address
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import rule, collect_rules
from pants.engine.target import FieldSet, Target, Targets, FieldSetsPerTarget, FieldSetsPerTargetRequest
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class TrivyDockerFieldSet(FieldSet):
    required_fields = (DockerImageSourceField,)

    source: DockerImageSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return False
        return tgt.get(SkipTrivyField).value


class TrivyDockerRequest(LintTargetsRequest):
    field_set_type = TrivyDockerFieldSet
    tool_subsystem = Trivy
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Lint Docker image with Trivy", level=LogLevel.DEBUG)
async def run_trivy_docker(
    request: TrivyDockerRequest.Batch[TrivyDockerRequest, Any],
) -> LintResult:

    assert len(request.elements) == 1, "not single element in partition"  # "Do we need to?"
    addrs = tuple(e.address for e in request.elements)

    tgts = await Get(Targets, Addresses(addrs))

    field_sets_per_tgt = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, tgts)
    )
    [field_set] = field_sets_per_tgt.field_sets

    package = await Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
    r = await run_trivy(RunTrivyRequest(
        command="image",
        scanners=(),
        target=package.artifacts[0].image_id,
        input_digest=EMPTY_DIGEST,
        description=f"Run Trivy on docker image {','.join(package.artifacts[0].tags)}"
    ))

    return LintResult.create(request, r)


def rules():
    return (
        *collect_rules(),
        *TrivyDockerRequest.rules()
    )