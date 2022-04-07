# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.helm.dependency_inference.chart import InferHelmChartDependenciesRequest
from pants.backend.helm.dependency_inference.chart import rules as chart_infer_rules
from pants.backend.helm.resolve import artifacts
from pants.backend.helm.target_types import (
    HelmArtifactTarget,
    HelmChartMetaSourceField,
    HelmChartTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.util_rules import chart
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
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
            *target_types_rules(),
            QueryRule(InferredDependencies, (InferHelmChartDependenciesRequest,)),
        ],
    )


def test_infer_chart_dependencies(rule_runner: RuleRunner) -> None:
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
            "src/bar/BUILD": """helm_chart()""",
            "src/bar/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: bar
                version: 0.1.0
                """
            ),
            "src/foo/BUILD": """helm_chart()""",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: foo
                version: 0.1.0
                dependencies:
                - name: cert-manager
                  repository: "@jetstack"
                - name: bar
                """
            ),
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

    tgt = rule_runner.get_target(Address("src/foo", target_name="foo"))
    inferred_deps = rule_runner.request(
        InferredDependencies, [InferHelmChartDependenciesRequest(tgt[HelmChartMetaSourceField])]
    )
    assert set(inferred_deps.dependencies) == {
        Address("3rdparty/helm/jetstack", target_name="cert-manager"),
        Address("src/bar", target_name="bar"),
    }


def test_raise_error_when_unknown_dependency_is_found(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": """helm_chart()""",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: foo
                version: 0.1.0
                dependencies:
                - name: bar
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    tgt = rule_runner.get_target(Address("src/foo", target_name="foo"))

    with pytest.raises(
        ExecutionError, match="Can not find any declared artifact for dependency 'bar'"
    ):
        rule_runner.request(
            InferredDependencies, [InferHelmChartDependenciesRequest(tgt[HelmChartMetaSourceField])]
        )
