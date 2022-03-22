# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.helm.dependency_inference.chart import InferHelmChartDependenciesRequest
from pants.backend.helm.dependency_inference.chart import rules as chart_infer_rules
from pants.backend.helm.resolve import artifacts
from pants.backend.helm.subsystems import helm
from pants.backend.helm.target_types import (
    HelmArtifactTarget,
    HelmChartMetaSourceField,
    HelmChartTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import chart
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget, HelmChartTarget],
        rules=[
            *artifacts.rules(),
            *chart.rules(),
            *chart_infer_rules(),
            *helm.rules(),
            *target_types_rules(),
            QueryRule(InferredDependencies, (InferHelmChartDependenciesRequest,)),
        ],
    )


def test_infer_3rparty_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/jetstack/BUILD": dedent(
                """\
                helm_artifact(
                  name="cert-manager",
                  repository="@jetstack",
                  artifact="cert-manager",
                  version="v0.7.0"
                )
                """
            ),
            "src/chart/BUILD": """helm_chart()""",
            "src/chart/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart2
                version: 0.1.0
                dependencies:
                - name: cert-manager
                  repository: "@jetstack"
                """
            ),
            "src/chart/values.yaml": HELM_VALUES_FILE,
            "src/chart/templates/service.yaml": K8S_SERVICE_FILE,
            "src/chart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
        }
    )

    source_root_patterns = ("/src/*",)
    repositories_opts = """{"jetstack": {"address": "https://charts.jetstack.io"}}"""
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
            f"--helm-classic-repositories={repositories_opts}",
        ]
    )

    tgt = rule_runner.get_target(Address("src/chart", target_name="chart"))

    inferred_deps = rule_runner.request(
        InferredDependencies, [InferHelmChartDependenciesRequest(tgt[HelmChartMetaSourceField])]
    )
    assert set(inferred_deps.dependencies) == {
        Address("3rdparty/helm/jetstack", target_name="cert-manager")
    }
