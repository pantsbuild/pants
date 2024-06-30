# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.helm.check.kubeconform import deployment
from pants.backend.helm.check.kubeconform.deployment import (
    KubeconformCheckDeploymentRequest,
    KubeconformDeploymentFieldSet,
)
from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_CRD_FILE,
    K8S_CUSTOM_RESOURCE_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.backend.helm.util_rules import chart, tool
from pants.backend.python.util_rules import pex
from pants.core.goals import package
from pants.core.goals.check import CheckResults
from pants.core.util_rules import config_files, external_tool, source_files, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *config_files.rules(),
            *chart.rules(),
            *external_tool.rules(),
            *deployment.rules(),
            *graph_rules(),
            *package.rules(),
            *pex.rules(),
            *process.rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            *target_types_rules(),
            QueryRule(CheckResults, (KubeconformCheckDeploymentRequest,)),
        ],
    )


__COMMON_TEST_FILES = {
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
}


def test_skip_check(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **__COMMON_TEST_FILES,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart', skip_kubeconform=True)",
        }
    )

    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)

    assert checked.exit_code == 0
    assert checked.checker_name == "kubeconform"
    assert len(checked.results) == 1
    assert checked.results[0].partition_description == addr.spec
    assert not checked.results[0].stdout


def test_valid_deployment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **__COMMON_TEST_FILES,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )
    rule_runner.set_options("--helm-infer-external-docker-images=['*']")

    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)

    assert checked.exit_code == 0
    assert checked.checker_name == "kubeconform"
    assert len(checked.results) == 1
    assert checked.results[0].partition_description == addr.spec
    assert (
        checked.results[0].stdout
        == "Summary: 2 resources found in 2 files - Valid: 2, Invalid: 0, Errors: 0, Skipped: 0\n"
    )


def test_invalid(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/templates/replication_controller.yml": dedent(
                """\
              apiVersion: v1
              kind: ReplicationController
              metadata:
                name: "bob"
              spec:
                replicas: asd"
                selector:
                  app: nginx
                templates:
                  metadata:
                    name: nginx
                    labels:
                      app: nginx
                  spec:
                    containers:
                    - name: nginx
                      image: nginx
                      ports:
                      - containerPort: 80
              """
            ),
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)

    assert checked.exit_code == 1
    assert len(checked.results) == 1
    assert checked.results[0].partition_description == addr.spec
    assert (
        "Summary: 1 resource found in 1 file - Valid: 0, Invalid: 1, Errors: 0, Skipped: 0"
        in checked.results[0].stdout
    )


def test_valid_deployment_ignoring_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **__COMMON_TEST_FILES,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name="foo",
                chart="//src/mychart",
                kubeconform_ignore_sources=[
                  "service.yaml"
                ]
              )
              """
            ),
        }
    )
    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)

    assert checked.exit_code == 0
    assert len(checked.results) == 1
    assert checked.results[0].partition_description == addr.spec
    assert (
        checked.results[0].stdout
        == "Summary: 1 resource found in 1 file - Valid: 1, Invalid: 0, Errors: 0, Skipped: 0\n"
    )


_CRD_TEST_FILES = {
    "src/mychart/BUILD": "helm_chart()",
    "src/mychart/Chart.yaml": HELM_CHART_FILE,
    "src/mychart/crds/myplatform.yaml": K8S_CRD_FILE,
    "src/mychart/templates/mycustom.yml": K8S_CUSTOM_RESOURCE_FILE,
}


def test_fail_using_crd(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_CRD_TEST_FILES,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)
    assert checked.exit_code == 1


def test_pass_using_crd_ignoring_schemas(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_CRD_TEST_FILES,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name='foo',
                chart='//src/mychart',
                kubeconform_ignore_missing_schemas=True
              )
              """
            ),
        }
    )

    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)
    assert checked.exit_code == 0


def test_pass_using_crd_skipping_kinds(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_CRD_TEST_FILES,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name='foo',
                chart='//src/mychart',
                kubeconform_skip_kinds=["MyPlatform"]
              )
              """
            ),
        }
    )

    addr = Address("src/deployment", target_name="foo")
    checked = run_check(rule_runner, addr)
    assert checked.exit_code == 0


def run_check(
    rule_runner: RuleRunner, address: Address, *, source_root_patterns: Iterable[str] = ("/src/*",)
) -> CheckResults:
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
            "--kubeconform-summary",
            "--helm-infer-external-docker-images=['*']",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    target = rule_runner.get_target(address)
    field_set = KubeconformDeploymentFieldSet.create(target)
    return rule_runner.request(CheckResults, [KubeconformCheckDeploymentRequest([field_set])])
