# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any

from pants.backend.terraform.dependencies import TerraformInitRequest, terraform_init
from pants.backend.terraform.dependency_inference import (
    TerraformDeploymentInvocationFilesRequest,
    get_terraform_backend_and_vars,
)
from pants.backend.terraform.target_types import (
    TerraformDependenciesField,
    TerraformDeploymentTarget,
    TerraformRootModuleField,
)
from pants.backend.tools.trivy.rules import RunTrivyRequest, run_trivy
from pants.backend.tools.trivy.subsystem import SkipTrivyField, Trivy
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.rules import collect_rules, rule
from pants.engine.target import DescriptionField, FieldSet, SourcesField, Target
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

    invocation_files = await get_terraform_backend_and_vars(
        TerraformDeploymentInvocationFilesRequest(fs.dependencies.address, fs.dependencies)
    )
    var_files = await determine_source_files(
        SourceFilesRequest(e.get(SourcesField) for e in invocation_files.vars_files)
    )

    command_args = []
    # Unlike Terraform, which needs the path to the vars file from the root module, Trivy needs the path from the cwd
    command_args.extend(["--tf-vars", ",".join(var_file for var_file in var_files.files)])

    input_digest = await merge_digests(
        MergeDigests([var_files.snapshot.digest, tf.sources_and_deps])
    )

    r = await run_trivy(
        RunTrivyRequest(
            command="config",
            scanners=(),
            command_args=tuple(command_args),
            target=tf.chdir,
            input_digest=input_digest,
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
