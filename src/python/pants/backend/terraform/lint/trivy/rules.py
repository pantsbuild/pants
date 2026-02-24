# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from abc import ABCMeta
from dataclasses import dataclass
from typing import Any, TypeGuard

from pants.backend.terraform.dependencies import (
    prepare_terraform_invocation,
    terraform_fieldset_to_init_request,
)
from pants.backend.terraform.dependency_inference import (
    TerraformDeploymentInvocationFilesRequest,
    get_terraform_backend_and_vars,
)
from pants.backend.terraform.target_types import (
    TerraformDeploymentFieldSet,
    TerraformDeploymentTarget,
    TerraformFieldSet,
    TerraformModuleTarget,
)
from pants.backend.tools.trivy.rules import RunTrivyRequest, run_trivy
from pants.backend.tools.trivy.subsystem import SkipTrivyField, Trivy
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSet, SourcesField, Target
from pants.util.logging import LogLevel


class TrivyLintTerraformRequest(LintTargetsRequest, metaclass=ABCMeta):
    tool_subsystem = Trivy  # type: ignore[assignment]


@dataclass(frozen=True)
class TrivyTerraformFieldSet(FieldSet, metaclass=ABCMeta):
    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTrivyField).value


@dataclass(frozen=True)
class RunTrivyOnTerraformRequest:
    field_set: TrivyTerraformFieldSet


def _is_terraform_deployment_field_set(fs: Any) -> TypeGuard[TerraformDeploymentFieldSet]:
    # This `isinstance` fails mypy and marks subsequent lines as unreachable inline in Python3.14
    # So, wrapped it in a typeguard
    return isinstance(fs, TerraformDeploymentFieldSet)


@rule
async def run_trivy_on_terraform(req: RunTrivyOnTerraformRequest) -> FallibleProcessResult:
    fs = req.field_set
    # Each subclass of TrivyTerraformFieldSet is a subclass of either TerraformDeploymentFieldSet or TerraformFieldSet
    tf = await prepare_terraform_invocation(terraform_fieldset_to_init_request(fs))  # type: ignore
    command_args: list[str] = []

    if _is_terraform_deployment_field_set(fs):
        # Only add vars files for deployments
        invocation_files = await get_terraform_backend_and_vars(
            TerraformDeploymentInvocationFilesRequest(fs.dependencies.address, fs.dependencies)
        )
        var_files = await determine_source_files(
            SourceFilesRequest(e.get(SourcesField) for e in invocation_files.vars_files)
        )

        # Unlike Terraform, which needs the path to the vars file from the root module, Trivy needs the path from the cwd
        command_args.extend(["--tf-vars", ",".join(var_file for var_file in var_files.files)])

        input_digest = await merge_digests(
            MergeDigests(
                [
                    var_files.snapshot.digest,
                    tf.terraform_sources.snapshot.digest,
                    tf.dependencies_files.snapshot.digest,
                ]
            ),
        )
    else:
        input_digest = await merge_digests(
            MergeDigests(
                [tf.terraform_sources.snapshot.digest, tf.dependencies_files.snapshot.digest]
            ),
        )

    return await run_trivy(
        RunTrivyRequest(
            command="config",
            scanners=(),
            command_args=tuple(command_args),
            target=tf.chdir,
            input_digest=input_digest,
            description=f"Run Trivy on terraform deployment {fs.address}",
        ),
        **implicitly(),
    )


@dataclass(frozen=True)
class TrivyLintTerraformDeploymentFieldSet(TerraformDeploymentFieldSet, TrivyTerraformFieldSet):
    pass


class TrivyLintTerraformDeploymentRequest(TrivyLintTerraformRequest):
    field_set_type = TrivyLintTerraformDeploymentFieldSet
    tool_subsystem = Trivy
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Lint Terraform deployment with Trivy", level=LogLevel.DEBUG)
async def run_trivy_on_terraform_deployment(
    request: TrivyLintTerraformDeploymentRequest.Batch[TrivyLintTerraformDeploymentFieldSet, Any],
) -> LintResult:
    assert len(request.elements) == 1, "not single element in partition"  # "Do we need to?"
    [fs] = request.elements

    return LintResult.create(request, await run_trivy_on_terraform(RunTrivyOnTerraformRequest(fs)))


@dataclass(frozen=True)
class TrivyLintTerraformModuleFieldSet(TerraformFieldSet, TrivyTerraformFieldSet):
    pass


class TrivyLintTerraformModuleRequest(TrivyLintTerraformRequest):
    field_set_type = TrivyLintTerraformModuleFieldSet
    tool_subsystem = Trivy
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Lint Terraform module with Trivy", level=LogLevel.DEBUG)
async def run_trivy_on_terraform_module(
    request: TrivyLintTerraformModuleRequest.Batch[TrivyLintTerraformModuleFieldSet, Any],
) -> LintResult:
    assert len(request.elements) == 1, "not single element in partition"  # "Do we need to?"
    [fs] = request.elements

    return LintResult.create(request, await run_trivy_on_terraform(RunTrivyOnTerraformRequest(fs)))


def rules():
    return (
        *collect_rules(),
        *TrivyLintTerraformDeploymentRequest.rules(),
        *TrivyLintTerraformModuleRequest.rules(),
        TerraformDeploymentTarget.register_plugin_field(SkipTrivyField),
        TerraformModuleTarget.register_plugin_field(SkipTrivyField),
    )
