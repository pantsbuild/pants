# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules import docker_build_context, dockerfile
from pants.backend.docker.util_rules.docker_build_args import docker_build_args
from pants.backend.docker.util_rules.docker_build_env import docker_build_environment_vars
from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.subsystem import HelmSubsystem
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
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import chart, deployment, render, sources, tool
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.deployment import (
    AnalysedDeployment,
    AnalyseDeploymentRequest,
    ContainerRef,
)
from pants.backend.helm.util_rules.render import RenderChartRequest, RenderedChart
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.backend.python.util_rules import pex
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.rules import QueryRule, SubsystemRule
from pants.engine.target import Dependencies, DependenciesRequest, Targets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *artifacts.rules(),
            *fetch.rules(),
            *chart.rules(),
            *dockerfile.rules(),
            *dockerfile_parser.rules(),
            *docker_build_context.rules(),
            docker_build_args,
            docker_build_environment_vars,
            *stripped_source_files.rules(),
            *pex.rules(),
            *process.rules(),
            *graph_rules(),
            *deployment.rules(),
            *render.rules(),
            *sources.rules(),
            *tool.rules(),
            SubsystemRule(HelmSubsystem),
            SubsystemRule(DockerOptions),
            QueryRule(HelmBinary, ()),
            QueryRule(HelmChart, (HelmChartFieldSet,)),
            QueryRule(Targets, (DependenciesRequest,)),
            QueryRule(RenderedChart, (RenderChartRequest,)),
            QueryRule(AnalysedDeployment, (AnalyseDeploymentRequest,)),
        ],
    )


def test_analyse_pod(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "mychart/BUILD": "helm_chart()",
            "mychart/Chart.yaml": HELM_CHART_FILE,
            "mychart/values.yaml": HELM_VALUES_FILE,
            "mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "mychart/templates/service.yaml": K8S_SERVICE_FILE,
            "mychart/templates/pod.yaml": dedent(
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
            "deployment/BUILD": "helm_deployment(name='foo', dependencies=['//mychart'])",
        }
    )

    source_root_patterns = ["/mychart", "/deployment"]
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])
    deployment_target = rule_runner.get_target(Address("deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(deployment_target)

    expected_container_refs = [
        ContainerRef(None, "busybox", "1.28"),
        ContainerRef(None, "busybox", "1.29"),
        ContainerRef("example.com", "containers/busybox", "1.28"),
    ]
    analysed_deployment = rule_runner.request(
        AnalysedDeployment, [AnalyseDeploymentRequest(field_set)]
    )

    assert analysed_deployment.container_images == tuple(expected_container_refs)


def test_analyse_deployment_dependencies(rule_runner: RuleRunner) -> None:
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
        env_inherit=set(["PATH", "PYENV_ROOT", "HOME"]),
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    dependencies = rule_runner.request(Targets, [DependenciesRequest(tgt.get(Dependencies))])

    expected_addresses = [
        Address("src/image", target_name="myapp"),
        Address("src/mychart", target_name="mychart"),
    ]
    addresses = [target.address for target in dependencies]

    assert addresses == expected_addresses
