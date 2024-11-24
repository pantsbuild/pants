# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any

from pants.backend.terraform.dependencies import TerraformInitRequest, terraform_init
from pants.backend.terraform.target_types import (
    TerraformDependenciesField,
    TerraformDeploymentTarget,
    TerraformRootModuleField,
)
from pants.backend.tools.trivy.rules import RunTrivyRequest, run_trivy
from pants.backend.tools.trivy.subsystem import SkipTrivyField, Trivy
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.rules import collect_rules, rule
from pants.engine.target import DescriptionField, FieldSet, Target
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class TrivyLintFieldSet(FieldSet):
    required_fields = (
        DescriptionField,
        TerraformRootModuleField,
        TerraformDependenciesField,
    )

    description: DescriptionField
    root_module: TerraformRootModuleField
    dependencies: TerraformDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTrivyField).value


class TrivyTerraformRequest(LintTargetsRequest):
    field_set_type = TrivyLintFieldSet
    tool_subsystem = Trivy
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


# TODO: terraform modules


@rule(desc="Lint Terraform deployment with Trivy", level=LogLevel.DEBUG)
async def run_trivy_on_terraform_deployment(
    request: TrivyTerraformRequest.Batch[TrivyTerraformRequest, Any]
) -> LintResult:
    assert len(request.elements) == 1, "not single element in partition"  # "Do we need to?"
    [fs] = request.elements

    tf = await terraform_init(
        TerraformInitRequest(
            fs.root_module,
            fs.dependencies,
            initialise_backend=False,  # TODO: do we need to initialise the backend?
        )
    )

    # TODO: add args file

    r = await run_trivy(
        RunTrivyRequest(
            command="config",
            scanners=(),
            command_args=(),
            target=tf.chdir,
            input_digest=tf.sources_and_deps,
            description=f"Run Trivy on terraform deployment {fs.address}",
        )
    )

    return LintResult.create(request, r)


def rules():
    return (
        *collect_rules(),
        *TrivyTerraformRequest.rules(),
        TerraformDeploymentTarget.register_plugin_field(SkipTrivyField),
    )
