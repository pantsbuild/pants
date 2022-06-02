# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.target_types import rules as docker_target_types_rules
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.dependency_inference.deployment import (
    AnalyseHelmDeploymentRequest,
    HelmDeploymentReport,
    InjectHelmDeploymentDependenciesRequest,
)
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmDeploymentDependenciesField,
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
from pants.backend.helm.util_rules.k8s import ImageRef
from pants.backend.python.util_rules import pex
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.rules import QueryRule, SubsystemRule
from pants.engine.target import InjectedDependencies
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *chart.rules(),
            *deployment.rules(),
            *dockerfile_parser.rules(),
            *docker_target_types_rules(),
            *graph_rules(),
            *pex.rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            SubsystemRule(DockerOptions),
            QueryRule(HelmDeploymentReport, (AnalyseHelmDeploymentRequest,)),
            QueryRule(InjectedDependencies, (InjectHelmDeploymentDependenciesRequest,)),
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
            "src/deployment/BUILD": "helm_deployment(name='foo', dependencies=['//src/mychart'])",
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(target)

    dependencies_report = rule_runner.request(
        HelmDeploymentReport, [AnalyseHelmDeploymentRequest(field_set)]
    )

    expected_container_refs = [
        ImageRef(registry=None, repository="busybox", tag="1.28"),
        ImageRef(registry=None, repository="busybox", tag="1.29"),
        ImageRef(registry="example.com", repository="containers/busybox", tag="1.28"),
    ]

    assert len(dependencies_report.container_images) == 3
    assert set(dependencies_report.container_images) == set(expected_container_refs)


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
                      image: myapp:latest
                """
            ),
            "src/deployment/BUILD": "helm_deployment(name='foo', dependencies=['//src/mychart'])",
            "src/image/BUILD": "docker_image(name='myapp')",
            "src/image/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    dependencies = rule_runner.request(
        InjectedDependencies,
        [InjectHelmDeploymentDependenciesRequest(tgt[HelmDeploymentDependenciesField])],
    )

    assert len(dependencies) == 1
    assert list(dependencies)[0] == Address("src/image", target_name="myapp")
