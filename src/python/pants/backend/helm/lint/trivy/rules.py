# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from abc import ABCMeta
from dataclasses import dataclass
from typing import Any, cast

from pants.backend.helm.subsystems.post_renderer import setup_post_renderer_launcher
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    RenderedHelmFiles,
    RenderHelmChartRequest,
    render_helm_chart,
    run_renderer,
)
from pants.backend.tools.trivy.rules import RunTrivyRequest, run_trivy
from pants.backend.tools.trivy.subsystem import SkipTrivyField, Trivy
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel


class TrivyLintHelmRequest(LintTargetsRequest, metaclass=ABCMeta):
    tool_subsystem = cast(type[SkippableSubsystem], Trivy)


@dataclass(frozen=True)
class TrivyHelmFieldSet(FieldSet, metaclass=ABCMeta):
    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTrivyField).value


@dataclass(frozen=True)
class RunTrivyOnHelmRequest:
    field_set: TrivyHelmFieldSet
    rendered_files: RenderedHelmFiles


@rule
async def run_trivy_on_helm(
    request: RunTrivyOnHelmRequest,
) -> FallibleProcessResult:
    """Run Trivy on Helm files, either a rendered Helm chart from a `helm_deployment` or a chart
    rendered from its defaults from a `helm_chart`"""

    r = await run_trivy(
        RunTrivyRequest(
            command="config",
            scanners=(),
            command_args=tuple(),
            target=".",  # the charts are rendered to the local directory
            input_digest=request.rendered_files.snapshot.digest,
            description=f"Run Trivy on Helm files for {request.field_set.address}",
        ),
        **implicitly(),
    )

    return r


@dataclass(frozen=True)
class TrivyLintHelmDeploymentFieldSet(HelmDeploymentFieldSet, TrivyHelmFieldSet):
    pass


class TrivyLintHelmDeploymentRequest(TrivyLintHelmRequest):
    field_set_type = TrivyLintHelmDeploymentFieldSet
    tool_subsystem = cast(type[SkippableSubsystem], Trivy)
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Lint Helm deployment with Trivy", level=LogLevel.DEBUG)
async def run_trivy_on_helm_deployment(
    request: TrivyLintHelmDeploymentRequest.Batch[TrivyLintHelmDeploymentFieldSet, Any],
) -> LintResult:
    assert len(request.elements) == 1, "not single element in partition"  # "Do we need to?"
    [field_set] = request.elements

    post_renderer = await setup_post_renderer_launcher(
        **implicitly(HelmDeploymentPostRendererRequest(field_set))
    )
    rendered_files = await run_renderer(
        **implicitly(
            HelmDeploymentRequest(
                field_set,
                cmd=HelmDeploymentCmd.RENDER,
                post_renderer=post_renderer,
                description=f"Evaluating Helm deployment files for {field_set.address}",
            )
        )
    )

    r = await run_trivy_on_helm(RunTrivyOnHelmRequest(field_set, rendered_files))

    return LintResult.create(request, r)


@dataclass(frozen=True)
class TrivyLintHelmChartFieldSet(HelmChartFieldSet, TrivyHelmFieldSet):
    pass


class TrivyLintHelmChartRequest(TrivyLintHelmRequest):
    field_set_type = TrivyLintHelmChartFieldSet
    tool_subsystem = cast(type[SkippableSubsystem], Trivy)
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Lint Helm chart with Trivy", level=LogLevel.DEBUG)
async def run_trivy_on_helm_chart(
    request: TrivyLintHelmChartRequest.Batch[TrivyLintHelmChartFieldSet, Any],
) -> LintResult:
    assert len(request.elements) == 1, "not single element in partition"  # "Do we need to?"
    [field_set] = request.elements

    rendered_files: RenderedHelmFiles = await render_helm_chart(RenderHelmChartRequest(field_set))
    r = await run_trivy_on_helm(RunTrivyOnHelmRequest(field_set, rendered_files))

    return LintResult.create(request, r)


def rules():
    return (
        *collect_rules(),
        *TrivyLintHelmDeploymentRequest.rules(),
        *TrivyLintHelmChartRequest.rules(),
        HelmDeploymentTarget.register_plugin_field(SkipTrivyField),
        HelmChartTarget.register_plugin_field(SkipTrivyField),
    )
