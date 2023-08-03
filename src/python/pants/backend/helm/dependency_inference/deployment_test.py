# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.dependency_inference.deployment import (
    AnalyseHelmDeploymentRequest,
    FirstPartyHelmDeploymentMapping,
    FirstPartyHelmDeploymentMappingRequest,
    HelmDeploymentReport,
    InferHelmDeploymentDependenciesRequest,
)
from pants.backend.helm.target_types import (
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
from pants.backend.helm.util_rules import chart, tool
from pants.backend.python.util_rules import pex
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *chart.rules(),
            *deployment.rules(),
            *graph_rules(),
            *pex.rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            QueryRule(FirstPartyHelmDeploymentMapping, (FirstPartyHelmDeploymentMappingRequest,)),
            QueryRule(HelmDeploymentReport, (AnalyseHelmDeploymentRequest,)),
            QueryRule(InferredDependencies, (InferHelmDeploymentDependenciesRequest,)),
        ],
    )


def test_deployment_dependencies_report(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: busybox:1.28
                  initContainers:
                    - name: init-service
                      image: busybox:1.29
                    - name: init-db
                      image: example.com/containers/busybox:1.28
                """
            ),
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"], env_inherit=PYTHON_BOOTSTRAP_ENV
    )

    target = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(target)

    dependencies_report = rule_runner.request(
        HelmDeploymentReport, [AnalyseHelmDeploymentRequest(field_set)]
    )

    expected_container_refs = [
        "busybox:1.28",
        "busybox:1.29",
        "example.com/containers/busybox:1.28",
    ]

    assert len(dependencies_report.all_image_refs) == 3
    assert set(dependencies_report.all_image_refs) == set(expected_container_refs)


def test_inject_chart_into_deployment_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    inferred_dependencies = rule_runner.request(
        InferredDependencies,
        [InferHelmDeploymentDependenciesRequest(field_set)],
    )

    assert len(inferred_dependencies.include) == 1
    assert list(inferred_dependencies.include)[0] == Address("src/mychart")


def test_resolve_relative_docker_addresses_to_deployment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": dedent(
                """\
                container:
                  image_ref: docker/image:latest
                """
            ),
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: {{ .Values.container.image_ref }}
                """
            ),
            "src/deployment/BUILD": dedent(
                """\
                docker_image(name="myapp")

                helm_deployment(
                    name="foo",
                    chart="//src/mychart",
                    values={
                        "container.image_ref": ":myapp"
                    }
                )
                """
            ),
            "src/deployment/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    expected_image_ref = ":myapp"
    expected_dependency_addr = Address("src/deployment", target_name="myapp")

    mapping = rule_runner.request(
        FirstPartyHelmDeploymentMapping, [FirstPartyHelmDeploymentMappingRequest(field_set)]
    )
    assert list(mapping.indexed_docker_addresses.values()) == [
        (expected_image_ref, expected_dependency_addr)
    ]


def test_inject_deployment_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: src/image:myapp
                """
            ),
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
            "src/image/BUILD": "docker_image(name='myapp')",
            "src/image/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    expected_image_ref = "src/image:myapp"
    expected_dependency_addr = Address("src/image", target_name="myapp")

    mapping = rule_runner.request(
        FirstPartyHelmDeploymentMapping, [FirstPartyHelmDeploymentMappingRequest(field_set)]
    )
    assert list(mapping.indexed_docker_addresses.values()) == [
        (expected_image_ref, expected_dependency_addr)
    ]

    inferred_dependencies = rule_runner.request(
        InferredDependencies,
        [InferHelmDeploymentDependenciesRequest(field_set)],
    )

    # The Helm chart dependency is part of the inferred dependencies
    assert len(inferred_dependencies.include) == 2
    assert expected_dependency_addr in inferred_dependencies.include


def test_disambiguate_docker_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: registry/image:latest
                """
            ),
            "src/deployment/BUILD": dedent(
                """\
                helm_deployment(
                    name="foo",
                    chart="//src/mychart",
                    dependencies=[
                        "!//registry/image:latest",
                    ]
                )
                """
            ),
            "registry/image/BUILD": "docker_image(name='latest')",
            "registry/image/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("/", "src/*")
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)

    inferred_dependencies = rule_runner.request(
        InferredDependencies,
        [InferHelmDeploymentDependenciesRequest(HelmDeploymentFieldSet.create(tgt))],
    )

    # Assert only the Helm chart dependency has been inferred
    assert len(inferred_dependencies.include) == 1
    assert set(inferred_dependencies.include) == {Address("src/mychart")}
