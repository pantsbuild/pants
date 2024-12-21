# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable, Mapping

import pytest

from pants.backend.k8s import k8s_subsystem, kubectl_tool
from pants.backend.k8s.goals.deploy import DeployK8sBundleFieldSet
from pants.backend.k8s.goals.deploy import rules as k8s_deploy_rules
from pants.backend.k8s.kubectl_tool import KubectlBinary
from pants.backend.k8s.target_types import K8sBundleTarget, K8sSourceTargetGenerator
from pants.core.goals.deploy import DeployProcess
from pants.engine.addresses import Address
from pants.engine.environment import EnvironmentName
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            K8sSourceTargetGenerator,
            K8sBundleTarget,
        ],
        rules=[
            *k8s_deploy_rules(),
            *k8s_subsystem.rules(),
            *kubectl_tool.rules(),
            QueryRule(KubectlBinary, (EnvironmentName,)),
            QueryRule(DeployProcess, (DeployK8sBundleFieldSet,)),
        ],
    )
    return rule_runner


def _get_process(
    rule_runner: RuleRunner,
    spec_path: str,
    target_name: str,
    *,
    args: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> DeployProcess:
    rule_runner.set_options(args or (), env=env)

    target = rule_runner.get_target(Address(spec_path, target_name=target_name))
    field_set = DeployK8sBundleFieldSet.create(target)

    return rule_runner.request(DeployProcess, [field_set])


def test_run_k8s_deploy(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/k8s/BUILD": dedent(
                """\
                k8s_sources()
                k8s_bundle(name="pod", dependencies=["pod.yaml"], context="local")
            """
            ),
            "src/k8s/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
            """
            ),
        }
    )

    deploy_process = _get_process(
        rule_runner,
        "src/k8s",
        "pod",
    )

    kubectl = rule_runner.request(KubectlBinary, [])

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
