# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.terraform.dependency_inference import (
    GetTerraformDependenciesRequest,
    TerraformDependencies,
)
from pants.backend.terraform.partition import partition_files_by_directory
from pants.backend.terraform.target_types import TerraformDeploymentFieldSet
from pants.backend.terraform.tool import TerraformProcess, TerraformTool
from pants.core.goals.deploy import DeployFieldSet, DeployProcess
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployTerraformFieldSet(TerraformDeploymentFieldSet, DeployFieldSet):
    pass


@dataclass(frozen=True)
class TerraformDeploymentRequest(EngineAwareParameter):
    field_set: TerraformDeploymentFieldSet

    extra_argv: tuple[str, ...]


@rule
async def prepare_terraform_deployment(
    request: TerraformDeploymentRequest,
) -> InteractiveProcess:
    source_files = await Get(SourceFiles, SourceFilesRequest([request.field_set.sources]))
    files_by_directory = partition_files_by_directory(source_files.files)

    fetched_deps = await Get(
        TerraformDependencies,
        GetTerraformDependenciesRequest(source_files, tuple(files_by_directory.keys())),
    )

    merged_fetched_deps = await Get(Digest, MergeDigests([x[1] for x in fetched_deps.fetched_deps]))

    sources_and_deps = await Get(
        Digest, MergeDigests([source_files.snapshot.digest, merged_fetched_deps])
    )

    process = await Get(
        Process,
        TerraformProcess(
            args=("apply",),
            input_digest=sources_and_deps,
            description="Terraform apply",
            chdir=next(iter(files_by_directory.keys())),
        ),
    )
    return InteractiveProcess.from_process(process)


@rule(desc="Run Terraform deploy process", level=LogLevel.DEBUG)
async def run_terraform_deploy(
    field_set: DeployTerraformFieldSet, terraform_subsystem: TerraformTool
) -> DeployProcess:
    interactive_process = await Get(
        InteractiveProcess, TerraformDeploymentRequest(field_set=field_set, extra_argv=tuple())
    )

    return DeployProcess(
        name=field_set.address.spec,
        process=interactive_process,
    )


def rules():
    return [*collect_rules(), UnionRule(DeployFieldSet, DeployTerraformFieldSet)]
