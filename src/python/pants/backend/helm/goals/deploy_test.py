# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.goals.deploy import DeployHelmDeploymentFieldSet
from pants.backend.helm.goals.deploy import rules as helm_deploy_rules
from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.backend.helm.testutil import HELM_CHART_FILE
from pants.backend.helm.util_rules import chart
from pants.backend.helm.util_rules import process as helm_process
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.deploy import DeployProcesses
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget],
        rules=[
            *chart.rules(),
            *external_tool.rules(),
            *helm_deploy_rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            *helm_process.rules(),
            QueryRule(HelmBinary, ()),
            QueryRule(DeployProcesses, (DeployHelmDeploymentFieldSet,)),
        ],
    )


def test_run_helm_deploy(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart/BUILD": """helm_chart(registries=["oci://www.example.com/external"])""",
            "src/chart/Chart.yaml": HELM_CHART_FILE,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name="foo",
                description="Foo deployment",
                namespace="uat",
                create_namespace=True,
                skip_crds=True,
                no_hooks=True,
                dependencies=["//src/chart"],
                sources=["*.yaml", "subdir/*.yml"],
                values={
                    "key": "foo"
                }
              )
              """
            ),
            "src/deployment/values.yaml": "",
            "src/deployment/override-values.yaml": "",
            "src/deployment/subdir/values.yml": "",
            "src/deployment/subdir/override-values.yml": "",
        }
    )

    source_root_patterns = ["/src/*"]
    deploy_args = ["--kubeconfig", "./kubeconfig"]
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
            f"--experimental-deploy-args={repr(deploy_args)}",
        ]
    )

    target = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = DeployHelmDeploymentFieldSet.create(target)

    helm = rule_runner.request(HelmBinary, [])
    deploy_processes = rule_runner.request(DeployProcesses, [field_set])

    assert len(deploy_processes) == 1
    assert deploy_processes[0].process
    assert deploy_processes[0].process.argv == (
        helm.path,
        "upgrade",
        "foo",
        "mychart",
        "--description",
        '"Foo deployment"',
        "--namespace",
        "uat",
        "--skip-crds",
        "--no-hooks",
        "--values",
        "values.yaml,subdir/values.yml,override-values.yaml,subdir/override-values.yml",
        "--set",
        "key=foo",
        "--install",
        "--create-namespace",
        "--kubeconfig",
        "./kubeconfig",
    )


def test_raises_error_when_using_invalid_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart/BUILD": """helm_chart(registries=["oci://www.example.com/external"])""",
            "src/chart/Chart.yaml": HELM_CHART_FILE,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name="bar",
                namespace="uat",
                dependencies=["//src/chart"],
                sources=["*.yaml", "subdir/*.yml"]
              )
              """
            ),
        }
    )

    source_root_patterns = ["/src/*"]
    deploy_args = ["--force", "--debug", "--kubeconfig=./kubeconfig", "--namespace", "foo"]
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
            f"--experimental-deploy-args={repr(deploy_args)}",
        ]
    )

    target = rule_runner.get_target(Address("src/deployment", target_name="bar"))
    field_set = DeployHelmDeploymentFieldSet.create(target)

    with pytest.raises(
        ExecutionError, match="The following command line arguments are not valid: --namespace foo."
    ):
        rule_runner.request(DeployProcesses, [field_set])
