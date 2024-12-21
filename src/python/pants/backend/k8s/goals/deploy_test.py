# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable, Mapping

import pytest

from pants.backend.k8s import k8s_subsystem, kubectl_subsystem
from pants.backend.k8s.goals.deploy import DeployK8sBundleFieldSet
from pants.backend.k8s.goals.deploy import rules as k8s_deploy_rules
from pants.backend.k8s.kubectl_subsystem import Kubectl
from pants.backend.k8s.target_types import K8sBundleTarget, K8sSourceTargetGenerator
from pants.core.goals.deploy import DeployProcess
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.platform import Platform
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
            *kubectl_subsystem.rules(),
            QueryRule(Kubectl, ()),
            QueryRule(Platform, ()),
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
                k8s_bundle(name="pod", sources=("src/k8s/pod.yaml",), context="local")
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
        rule_runner, "src/k8s", "pod", args=("--k8s-available-contexts=['local']",)
    )

    kubectl = rule_runner.request(Kubectl, [])
    platform = rule_runner.request(Platform, [])

    assert deploy_process.process
    assert deploy_process.process.process.argv == (
        kubectl.generate_exe(platform),
        "--context",
        "local",
        "apply",
        "-o",
        "yaml",
        "-f",
        "src/k8s/pod.yaml",
    )


def test_context_validation(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/k8s/BUILD": dedent(
                """\
                k8s_sources()
                k8s_bundle(name="pod", sources=("src/k8s/pod.yaml",), context="local")
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

    with pytest.raises(
        ExecutionError,
        match=r"ValueError: Context `local` is not listed in `\[k8s\].available_contexts`",
    ):
        _get_process(
            rule_runner,
            "src/k8s",
            "pod",
        )
