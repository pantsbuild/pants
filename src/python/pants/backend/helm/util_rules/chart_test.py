# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import (
    HelmArtifactTarget,
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
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
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmArtifactTarget, HelmDeploymentTarget],
        rules=[
            *chart.rules(),
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
    assert helm_chart.info == expected_metadata
    assert len(helm_chart.snapshot.files) == 4
    assert helm_chart.address == address


def test_override_metadata_version(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo', version='2.0.0')",
            "Chart.yaml": gen_chart_file("foo", version="1.0.0"),
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    expected_metadata = HelmChartMetadata(
        name="foo",
        version="2.0.0",
    )

    address = Address("", target_name="foo")
    tgt = rule_runner.get_target(address)

    helm_chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(tgt)])
    assert not helm_chart.artifact
    assert helm_chart.info == expected_metadata


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

    target = rule_runner.get_target(Address("src/chart2", target_name="chart2"))
    helm_chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    assert "charts/chart1" in helm_chart.snapshot.dirs
    assert "charts/chart1/templates/service.yaml" in helm_chart.snapshot.files
    assert len(helm_chart.info.dependencies) == 1
    assert helm_chart.info.dependencies[0].name == "chart1"
    assert helm_chart.info.dependencies[0].alias == "foo"


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

    assert helm_chart.info == expected_metadata
    assert "charts/chart1" in helm_chart.snapshot.dirs
    assert "charts/chart1/templates/service.yaml" in helm_chart.snapshot.files
    assert "charts/cert-manager" in helm_chart.snapshot.dirs
    assert "charts/cert-manager/Chart.yaml" in helm_chart.snapshot.files


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
            )
        ],
    )

    assert helm_chart.info == expected_metadata
    assert new_metadata == expected_metadata


def test_obtain_chart_from_deployment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/BUILD": dedent(
                """\
                helm_artifact(
                  name="cert-manager",
                  repository="https://charts.jetstack.io/",
                  artifact="cert-manager",
                  version="v1.7.1"
                )
                """
            ),
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": gen_chart_file("foo", version="1.0.0"),
            "src/deploy/BUILD": dedent(
                """\
                helm_deployment(name="first_party", chart="//src/foo")

                helm_deployment(name="3rd_party", chart="//3rdparty/helm:cert-manager")
                """
            ),
        }
    )

    first_party_target = rule_runner.get_target(Address("src/deploy", target_name="first_party"))
    third_party_target = rule_runner.get_target(Address("src/deploy", target_name="3rd_party"))

    first_party_chart = rule_runner.request(
        HelmChart, [FindHelmDeploymentChart(HelmDeploymentFieldSet.create(first_party_target))]
    )
    assert first_party_chart.info.name == "foo"
    assert first_party_chart.info.version == "1.0.0"
    assert not first_party_chart.artifact

    third_party_chart = rule_runner.request(
        HelmChart, [FindHelmDeploymentChart(HelmDeploymentFieldSet.create(third_party_target))]
    )
    assert third_party_chart.info.name == "cert-manager"
    assert third_party_chart.info.version == "v1.7.1"
    assert third_party_chart.artifact
