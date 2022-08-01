# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.helm.goals.deploy import DeployHelmDeploymentFieldSet
from pants.backend.helm.goals.deploy import rules as helm_deploy_rules
from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.backend.helm.testutil import HELM_CHART_FILE
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.deploy import DeployProcess
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *helm_deploy_rules(),
            QueryRule(HelmBinary, ()),
            QueryRule(DeployProcess, (DeployHelmDeploymentFieldSet,)),
        ],
    )
    return rule_runner


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
                dependencies=["//src/chart", "//src/docker/myimage"],
                sources=["common.yaml", "*.yaml", "*-override.yaml", "subdir/*.yaml",  "subdir/*-override.yaml", "subdir/last.yaml"],
                values={
                    "key": "foo",
                    "amount": "300",
                    "long_string": "This is a long string",
                },
                timeout=150,
              )
              """
            ),
            "src/deployment/common.yaml": "",
            "src/deployment/bar-override.yaml": "",
            "src/deployment/foo.yaml": "",
            "src/deployment/bar.yaml": "",
            "src/deployment/subdir/foo.yaml": "",
            "src/deployment/subdir/foo-override.yaml": "",
            "src/deployment/subdir/bar.yaml": "",
            "src/deployment/subdir/last.yaml": "",
            "src/docker/myimage/BUILD": dedent(
                """\
                docker_image(registries=["https://wwww.example.com"], repository="myimage")
                """
            ),
            "src/docker/myimage/Dockerfile": dedent(
                """\
                FROM busybox
                """
            ),
        }
    )

    source_root_patterns = ["/src/*"]
    deploy_args = ["--kubeconfig", "./kubeconfig"]
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
            f"--experimental-deploy-args={repr(deploy_args)}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    target = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = DeployHelmDeploymentFieldSet.create(target)

    helm = rule_runner.request(HelmBinary, [])
    deploy_process = rule_runner.request(DeployProcess, [field_set])

    assert deploy_process.process
    assert deploy_process.process.process.argv == (
        helm.path,
        "upgrade",
        "foo",
        "mychart",
        "--description",
        '"Foo deployment"',
        "--namespace",
        "uat",
        "--create-namespace",
        "--skip-crds",
        "--no-hooks",
        "--post-renderer",
        "./post_renderer_wrapper.sh",
        "--values",
        "common.yaml,bar.yaml,foo.yaml,bar-override.yaml,subdir/bar.yml,subdir/foo.yaml,subdir/foo-override.yaml,subdir/last.yml",
        "--set",
        "key=foo",
        "--set",
        "amount=300",
        "--set",
        'long_string="This is a long string"',
        "--install",
        "--timeout",
        "150s",
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
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    target = rule_runner.get_target(Address("src/deployment", target_name="bar"))
    field_set = DeployHelmDeploymentFieldSet.create(target)

    with pytest.raises(
        ExecutionError, match="The following command line arguments are not valid: --namespace foo."
    ):
        rule_runner.request(DeployProcess, [field_set])
