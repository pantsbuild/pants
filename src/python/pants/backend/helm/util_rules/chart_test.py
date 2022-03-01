# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import HelmArtifactTarget, HelmChartTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
    gen_chart_file,
)
from pants.backend.helm.util_rules import chart
from pants.backend.helm.util_rules.chart import FindHelmDeploymentChart, HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.chart_metadata import (
    ChartType,
    HelmChartDependency,
    HelmChartMetadata,
    ParseHelmChartMetadataDigest,
)
from pants.build_graph.address import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmArtifactTarget, HelmDeploymentTarget],
        rules=[
            *chart.rules(),
            *sources.rules(),
            *tool.rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            *target_types_rules(),
            QueryRule(HelmChart, (HelmChartRequest,)),
            QueryRule(HelmChartMetadata, (ParseHelmChartMetadataDigest,)),
            QueryRule(HelmChart, (FindHelmDeploymentChart,)),
        ],
    )


_TEST_CHART_COLLECT_SOURCES_PARAMS = [
    ("foo", "0.1.0", ChartType.APPLICATION, "https://www.example.com/icon.png"),
    ("bar", "0.2.0", ChartType.LIBRARY, None),
]


@pytest.mark.parametrize("name, version, type, icon", _TEST_CHART_COLLECT_SOURCES_PARAMS)
def test_collects_single_chart_sources(
    rule_runner: RuleRunner,
    name: str,
    version: str,
    type: ChartType,
    icon: str | None,
) -> None:
    rule_runner.write_files(
        {
            "BUILD": f"helm_chart(name='{name}')",
            "Chart.yaml": gen_chart_file(name, version=version, type=type, icon=icon),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    address = Address("", target_name=name)
    tgt = rule_runner.get_target(address)

    expected_metadata = HelmChartMetadata(
        name=name,
        version=version,
        icon=icon,
        type=type,
    )

    helm_chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(tgt)])
    assert not helm_chart.artifact
    assert helm_chart.metadata == expected_metadata
    assert len(helm_chart.snapshot.files) == 4
    assert helm_chart.address == address
    assert helm_chart.lint_strict == lint_strict


def test_gathers_local_subchart_sources_using_explicit_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart1/BUILD": "helm_chart()",
            "src/chart1/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart1
                version: 0.1.0
                """
            ),
            "src/chart1/values.yaml": HELM_VALUES_FILE,
            "src/chart1/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart1/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/chart2/BUILD": "helm_chart(dependencies=['//src/chart1'])",
            "src/chart2/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart2
                version: 0.1.0
                dependencies:
                - name: chart1
                  alias: foo
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))
    helm_chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    assert "chart2/charts/chart1" in helm_chart.snapshot.dirs
    assert "chart2/charts/chart1/templates/service.yaml" in helm_chart.snapshot.files
    assert len(helm_chart.metadata.dependencies) == 1
    assert helm_chart.metadata.dependencies[0].name == "chart1"
    assert helm_chart.metadata.dependencies[0].alias == "foo"


def test_gathers_all_subchart_sources_inferring_dependencies(rule_runner: RuleRunner) -> None:
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
            "src/chart1/BUILD": "helm_chart()",
            "src/chart1/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart1
                version: 0.1.0
                """
            ),
            "src/chart1/values.yaml": HELM_VALUES_FILE,
            "src/chart1/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/chart1/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/chart2/BUILD": "helm_chart()",
            "src/chart2/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart2
                version: 0.1.0
                dependencies:
                - name: chart1
                  alias: dep1
                - name: cert-manager
                  repository: "https://charts.jetstack.io"
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
        ]
    )

    expected_metadata = HelmChartMetadata(
        name="chart2",
        api_version="v2",
        version="0.1.0",
        dependencies=(
            HelmChartDependency(
                name="chart1",
                alias="dep1",
                version="0.1.0",
            ),
            HelmChartDependency(
                name="cert-manager", repository="https://charts.jetstack.io", version="v0.7.0"
            ),
        ),
    )

    target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))
    helm_chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    assert helm_chart.metadata == expected_metadata
    assert "chart2/charts/chart1" in helm_chart.snapshot.dirs
    assert "chart2/charts/chart1/templates/service.yaml" in helm_chart.snapshot.files
    assert "chart2/charts/cert-manager" in helm_chart.snapshot.dirs
    assert "chart2/charts/cert-manager/Chart.yaml" in helm_chart.snapshot.files


def test_chart_metadata_is_updated_with_explicit_dependencies(rule_runner: RuleRunner) -> None:
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
            "src/chart1/BUILD": "helm_chart()",
            "src/chart1/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart1
                version: 0.1.0
                """
            ),
            "src/chart2/BUILD": dedent(
                """\
                helm_chart(dependencies=["//src/chart1", "//3rdparty/helm/jetstack:cert-manager"])
                """
            ),
            "src/chart2/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart2
                version: 0.1.0
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
        ]
    )

    expected_metadata = HelmChartMetadata(
        name="chart2",
        api_version="v2",
        version="0.1.0",
        dependencies=(
            HelmChartDependency(
                name="chart1",
                version="0.1.0",
            ),
            HelmChartDependency(
                name="cert-manager", version="v0.7.0", repository="https://charts.jetstack.io"
            ),
        ),
    )

    target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))
    helm_chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])
    new_metadata = rule_runner.request(
        HelmChartMetadata,
        [
            ParseHelmChartMetadataDigest(
                helm_chart.snapshot.digest,
                description_of_origin="test_chart_metadata_is_updated_with_explicit_dependencies",
                prefix=helm_chart.path,
            )
        ],
    )

    assert helm_chart.metadata == expected_metadata
    assert new_metadata == expected_metadata


def test_obtain_chart_from_deployment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": gen_chart_file("foo", version="1.0.0"),
            "src/bar/BUILD": dedent(
                """\
                helm_deployment(dependencies=["//src/foo"])
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/bar"))
    field_set = HelmDeploymentFieldSet.create(target)

    chart = rule_runner.request(HelmChart, [FindHelmDeploymentChart(field_set)])

    assert chart.metadata.name == "foo"
    assert chart.metadata.version == "1.0.0"


def test_fail_when_no_chart_dependency_is_found(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": """helm_deployment(name="foo")"""})

    target = rule_runner.get_target(Address("", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(target)

    msg = f"The target '{field_set.address}' is missing a dependency on a `helm_chart` target."
    with pytest.raises(ExecutionError, match=msg):
        rule_runner.request(HelmChart, [FindHelmDeploymentChart(field_set)])


def test_fail_when_more_than_one_chart_is_found(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": gen_chart_file("foo", version="1.0.0"),
            "src/bar/BUILD": "helm_chart()",
            "src/bar/Chart.yaml": gen_chart_file("bar", version="1.0.3"),
            "src/quxx/BUILD": dedent(
                """\
                helm_deployment(dependencies=["//src/foo", "//src/bar"])
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/quxx"))
    field_set = HelmDeploymentFieldSet.create(target)

    msg = (
        f"The target '{field_set.address}' has too many `{HelmChartTarget.alias}` "
        "addresses in its dependencies, it should have only one."
    )
    with pytest.raises(ExecutionError, match=msg):
        rule_runner.request(HelmChart, [FindHelmDeploymentChart(field_set)])
