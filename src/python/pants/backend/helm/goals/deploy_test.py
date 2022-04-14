# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.goals.deploy import DeployHelmDeploymentFieldSet
from pants.backend.helm.goals.deploy import rules as helm_deploy_rules
from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.backend.helm.testutil import HELM_CHART_FILE
from pants.backend.helm.util_rules import chart, tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.deploy import DeployProcesses
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
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
            *tool.rules(),
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
                name="awesome",
                namespace="uat",
                dependencies=["//src/chart"],
                sources=["*.yaml", "subdir/*.yml"]
              )
              """
            ),
            "src/deployment/values.yaml": "",
            "src/deployment/override-values.yaml": "",
            "src/deployment/subdir/values.yml": "",
        }
    )

    source_root_patterns = ["/src/*"]
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/deployment", target_name="awesome"))
    field_set = DeployHelmDeploymentFieldSet.create(target)

    helm = rule_runner.request(HelmBinary, [])
    install_processes = rule_runner.request(DeployProcesses, [field_set])

    assert len(install_processes) == 1
    assert install_processes[0].process
    assert install_processes[0].process.argv == (
        helm.path,
        "upgrade",
        "awesome",
        "mychart",
        "--install",
        "--namespace",
        "uat",
        "--values",
        "values.yaml,subdir/values.yml,override-values.yaml",
    )
