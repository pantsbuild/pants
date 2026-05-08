# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

import pants.backend.helm.dependency_inference.chart
import pants.backend.helm.dependency_inference.deployment
import pants.backend.helm.util_rules.chart
import pants.backend.helm.util_rules.tool
import pants.backend.tools.trivy.rules
from pants.backend.helm.lint.trivy.rules import (
    TrivyLintHelmChartRequest,
    TrivyLintHelmDeploymentRequest,
)
from pants.backend.helm.lint.trivy.rules import rules as trivy_helm_rules
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.backend.helm.util_rules import post_renderer
from pants.backend.tools.semgrep.rules import PartitionMetadata
from pants.backend.tools.trivy.testutil import assert_trivy_output, trivy_config
from pants.core.goals import package
from pants.core.goals.lint import LintResult
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

K8S_POD_TEMPLATE = """
---
apiVersion: v1
kind: Pod
metadata:
  name: privileged-pod
  labels:
    app: test-app
spec:
  containers:
  - name: test-container
    image: nginx:latest
    securityContext:
      privileged: true
      capabilities:
        add: ["ALL"] # Explicitly add all capabilities
        drop: {{ .Values.drop }}     # Parametrisation allows us to fix this in the deployment
"""


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget],
        rules=[
            # Trivy rules
            *pants.backend.tools.trivy.rules.rules(),
            *trivy_helm_rules(),
            # Helm rules
            *pants.backend.helm.dependency_inference.deployment.rules(),
            *post_renderer.rules(),
            *pants.backend.helm.util_rules.chart.rules(),
            *pants.backend.helm.util_rules.tool.rules(),
            # Core rules
            *package.rules(),
            # Query
            QueryRule(LintResult, (TrivyLintHelmChartRequest.Batch,)),
            QueryRule(LintResult, (TrivyLintHelmDeploymentRequest.Batch,)),
        ],
    )

    rule_runner.write_files(
        {
            "src/mychart/BUILD": dedent(
                """
            helm_chart(name="mychart"),
            helm_deployment(
                name="mydeployment",
                chart=":mychart",
                values={
                    "drop": "[ALL]"
                }
            ),
        """
            ),
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/mychart/templates/pod.yaml": K8S_POD_TEMPLATE,
            "trivy.yaml": trivy_config,
        }
    )
    rule_runner.set_options(("--helm-infer-external-docker-images=['nginx:latest']",))

    return rule_runner


def test_trivy_lint_chart(rule_runner: RuleRunner) -> None:
    tgt = rule_runner.get_target(Address("src/mychart", target_name="mychart"))

    result = rule_runner.request(
        LintResult,
        [
            TrivyLintHelmChartRequest.Batch(
                "helm", (HelmChartFieldSet.create(tgt),), PartitionMetadata
            )
        ],
    )

    assert_trivy_output(result, 1, "mychart/templates/pod.yaml", "config", 16)


def test_trivy_lint_deployment(rule_runner: RuleRunner) -> None:
    tgt = rule_runner.get_target(Address("src/mychart", target_name="mydeployment"))

    result = rule_runner.request(
        LintResult,
        [
            TrivyLintHelmDeploymentRequest.Batch(
                "helm", (HelmDeploymentFieldSet.create(tgt),), PartitionMetadata
            )
        ],
    )

    assert_trivy_output(result, 1, "mychart/templates/pod.yaml", "config", 15)
