# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable, Mapping

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.helm.goals.deploy import DeployHelmDeploymentFieldSet
from pants.backend.helm.goals.deploy import rules as helm_deploy_rules
from pants.backend.helm.target_types import (
    HelmArtifactTarget,
    HelmChartTarget,
    HelmDeploymentTarget,
)
from pants.backend.helm.testutil import HELM_CHART_FILE
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals import package
from pants.core.goals.deploy import DeployProcess
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmArtifactTarget, HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *helm_deploy_rules(),
            *source_files.rules(),
            *package.rules(),
            QueryRule(HelmBinary, ()),
            QueryRule(DeployProcess, (DeployHelmDeploymentFieldSet,)),
        ],
    )
    return rule_runner


def _run_deployment(
    rule_runner: RuleRunner,
    spec_path: str,
    target_name: str,
    *,
    args: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> DeployProcess:
    rule_runner.set_options(args or (), env=env, env_inherit=PYTHON_BOOTSTRAP_ENV)

    target = rule_runner.get_target(Address(spec_path, target_name=target_name))
    field_set = DeployHelmDeploymentFieldSet.create(target)

    return rule_runner.request(DeployProcess, [field_set])


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
                namespace=f"uat-{env('NS_SUFFIX')}",
                skip_crds=True,
                no_hooks=True,
                chart="//src/chart",
                dependencies=["//src/docker/myimage"],
                sources=["common.yaml", "*.yaml", "*-override.yaml", "subdir/*.yaml", "subdir/*-override.yaml", "subdir/last.yaml"],
                values={
                    "key": "foo",
                    "amount": "300",
                    "long_string": "This is a long string",
                    "build_number": f"{env('BUILD_NUMBER')}",
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

    expected_build_number = "34"
    expected_ns_suffix = "quxx"
    expected_value_files_order = [
        "common.yaml",
        "bar.yaml",
        "foo.yaml",
        "bar-override.yaml",
        "subdir/bar.yaml",
        "subdir/foo.yaml",
        "subdir/foo-override.yaml",
        "subdir/last.yaml",
    ]

    deploy_args = ["--kubeconfig", "./kubeconfig", "--create-namespace"]
    deploy_process = _run_deployment(
        rule_runner,
        "src/deployment",
        "foo",
        args=[f"--helm-args={repr(deploy_args)}"],
        env={"BUILD_NUMBER": expected_build_number, "NS_SUFFIX": expected_ns_suffix},
    )

    helm = rule_runner.request(HelmBinary, [])

    assert deploy_process.process
    assert deploy_process.process.process.argv == (
        helm.path,
        "upgrade",
        "foo",
        "mychart",
        "--description",
        '"Foo deployment"',
        "--namespace",
        f"uat-{expected_ns_suffix}",
        "--skip-crds",
        "--no-hooks",
        "--post-renderer",
        "./post_renderer_wrapper.sh",
        "--values",
        ",".join(
            [f"__values/src/deployment/{filename}" for filename in expected_value_files_order]
        ),
        "--set",
        "key=foo",
        "--set",
        "amount=300",
        "--set",
        'long_string="This is a long string"',
        "--set",
        f"build_number={expected_build_number}",
        "--install",
        "--timeout",
        "150s",
        "--kubeconfig",
        "./kubeconfig",
        "--create-namespace",
    )


@pytest.mark.parametrize("invalid_passthrough_args", [["--namespace", "foo"], ["--dry-run"]])
def test_raises_error_when_using_invalid_passthrough_args(
    rule_runner: RuleRunner, invalid_passthrough_args: list[str]
) -> None:
    rule_runner.write_files(
        {
            "src/chart/BUILD": """helm_chart(registries=["oci://www.example.com/external"])""",
            "src/chart/Chart.yaml": HELM_CHART_FILE,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name="bar",
                namespace="uat",
                chart="//src/chart",
                sources=["*.yaml", "subdir/*.yml"]
              )
              """
            ),
        }
    )

    source_root_patterns = ["/src/*"]
    deploy_args = ["--force", "--debug", "--kubeconfig=./kubeconfig", *invalid_passthrough_args]

    invalid_passthrough_args_as_string = " ".join(invalid_passthrough_args)
    with pytest.raises(
        ExecutionError,
        match=f"The following command line arguments are not valid: {invalid_passthrough_args_as_string}.",
    ):
        _run_deployment(
            rule_runner,
            "src/deployment",
            "bar",
            args=[
                f"--source-root-patterns={repr(source_root_patterns)}",
                f"--helm-args={repr(deploy_args)}",
            ],
        )


def test_can_deploy_3rd_party_chart(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/BUILD": dedent(
                """\
                helm_artifact(
                    name="prometheus-stack",
                    repository="https://prometheus-community.github.io/helm-charts",
                    artifact="kube-prometheus-stack",
                    version="^27.2.0"
                )
                """
            ),
            "BUILD": dedent(
                """\
              helm_deployment(
                name="deploy_3rd_party",
                chart="//3rdparty/helm:prometheus-stack",
              )
              """
            ),
        }
    )
    deploy_process = _run_deployment(
        rule_runner,
        "",
        "deploy_3rd_party",
        args=[
            "--helm-infer-external-docker-images=['quay.io/kiwigrid/k8s-sidecar','grafana/grafana','bats/bats','k8s.gcr.io/kube-state-metrics/kube-state-metrics','quay.io/prometheus/node-exporter','quay.io/prometheus-operator/prometheus-operator']"
        ],
    )

    assert deploy_process.process
    assert len(deploy_process.publish_dependencies) == 0


@pytest.mark.parametrize(
    "dry_run_args,expected",
    [
        ([], False),
        (["--experimental-deploy-dry-run=False"], False),
        (["--experimental-deploy-dry-run"], True),
    ],
)
def test_run_helm_deploy_adheres_to_dry_run_flag(
    rule_runner: RuleRunner, dry_run_args: list[str], expected: bool
) -> None:
    rule_runner.write_files(
        {
            "src/chart/BUILD": """helm_chart(registries=["oci://www.example.com/external"])""",
            "src/chart/Chart.yaml": HELM_CHART_FILE,
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name="bar",
                namespace="uat",
                chart="//src/chart",
                sources=["*.yaml", "subdir/*.yml"]
              )
              """
            ),
        }
    )

    expected_build_number = "34"
    expected_ns_suffix = "quxx"

    deploy_args = ["--kubeconfig", "./kubeconfig", "--create-namespace"]
    deploy_process = _run_deployment(
        rule_runner,
        "src/deployment",
        "bar",
        args=[f"--helm-args={repr(deploy_args)}", *dry_run_args],
        env={"BUILD_NUMBER": expected_build_number, "NS_SUFFIX": expected_ns_suffix},
    )

    assert deploy_process.process
    assert ("--dry-run" in deploy_process.process.process.argv) == expected
