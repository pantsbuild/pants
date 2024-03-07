# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.helm.dependency_inference.chart import (
    FirstPartyHelmChartMapping,
    HelmChartDependenciesInferenceFieldSet,
    InferHelmChartDependenciesRequest,
    resolve_dependency_url,
)
from pants.backend.helm.dependency_inference.chart import rules as chart_infer_rules
from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.remotes import HelmRemotes
from pants.backend.helm.target_types import HelmArtifactTarget, HelmChartTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.util_rules import chart
from pants.backend.helm.util_rules.chart_metadata import HelmChartDependency
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmArtifactTarget, HelmChartTarget],
        rules=[
            *artifacts.rules(),
            *chart.rules(),
            *chart_infer_rules(),
            *target_types_rules(),
            QueryRule(FirstPartyHelmChartMapping, ()),
            QueryRule(InferredDependencies, (InferHelmChartDependenciesRequest,)),
        ],
    )
    return rule_runner


def test_build_first_party_mapping(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart(name='foo')",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart-name
                version: 0.1.0
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/foo", target_name="foo"))
    mapping = rule_runner.request(FirstPartyHelmChartMapping, [])
    assert mapping["chart-name"] == tgt.address


def test_duplicate_first_party_mappings(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart-name
                version: 0.1.0
                """
            ),
            "src/bar/BUILD": "helm_chart()",
            "src/bar/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart-name
                version: 0.1.0
                """
            ),
        }
    )

    expected_err_msg = (
        "Found more than one `helm_chart` target using the same chart name:\n\n"
        f"{bullet_list(['src/bar:bar -> chart-name', 'src/foo:foo -> chart-name'])}"
    )

    with pytest.raises(ExecutionError) as err_info:
        rule_runner.request(FirstPartyHelmChartMapping, [])

    assert expected_err_msg in err_info.value.args[0]


def test_infer_chart_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/jetstack/BUILD": dedent(
                """\
                helm_artifact(
                  name="cert-manager",
                  repository="https://charts.jetstack.io",
                  artifact="cert-manager",
                  version="v0.7.0"
                )
                """
            ),
            "src/foo/BUILD": """helm_chart(dependencies=["//src/quxx"])""",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: foo
                version: 0.1.0
                dependencies:
                - name: cert-manager
                  repository: "https://charts.jetstack.io"
                - name: bar
                - name: quxx
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
            "src/quxx/BUILD": """helm_chart()""",
            "src/quxx/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: quxx
                version: 0.1.0
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/foo", target_name="foo"))
    inferred_deps = rule_runner.request(
        InferredDependencies,
        [InferHelmChartDependenciesRequest(HelmChartDependenciesInferenceFieldSet.create(tgt))],
    )
    assert inferred_deps == InferredDependencies(
        [
            Address("3rdparty/helm/jetstack", target_name="cert-manager"),
            Address("src/bar", target_name="bar"),
        ]
    )


def test_disambiguate_chart_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/bar/BUILD": dedent(
                """\
                helm_artifact(artifact="bar", version="0.1.0", registry="oci://example.com/charts")
                """
            ),
            "src/foo/BUILD": """helm_chart(dependencies=["!//3rdparty/bar"])""",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: foo
                version: 0.1.0
                dependencies:
                - name: bar
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
        }
    )

    tgt = rule_runner.get_target(Address("src/foo", target_name="foo"))
    inferred_deps = rule_runner.request(
        InferredDependencies,
        [InferHelmChartDependenciesRequest(HelmChartDependenciesInferenceFieldSet.create(tgt))],
    )
    assert inferred_deps == InferredDependencies(
        [
            Address("src/bar", target_name="bar"),
        ]
    )


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

    tgt = rule_runner.get_target(Address("src/foo", target_name="foo"))

    with pytest.raises(
        ExecutionError, match="Can not find any declared artifact for dependency 'bar'"
    ):
        rule_runner.request(
            InferredDependencies,
            [InferHelmChartDependenciesRequest(HelmChartDependenciesInferenceFieldSet.create(tgt))],
        )


@pytest.mark.parametrize(
    "dependency,expected",
    [
        (
            HelmChartDependency(repository="https://repo.example.com", name="name"),
            "https://repo.example.com/name",
        ),
        (
            HelmChartDependency(repository="https://repo.example.com/", name="name"),
            "https://repo.example.com/name",
        ),
    ],
)
def test_18629(dependency, expected) -> None:
    """Test that we properly resolve dependency urls."""
    assert resolve_dependency_url(HelmRemotes(tuple(), FrozenDict()), dependency) == expected
