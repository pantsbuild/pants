# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.goals.install import InstallHelmDeploymentFieldSet
from pants.backend.helm.goals.install import rules as install_rules
from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.backend.helm.testutil import HELM_CHART_FILE
from pants.backend.helm.util_rules import chart, sources, tool
from pants.backend.helm.util_rules.deployment import get_chart_via_deployment
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.install import InstallProcesses
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.rules import SubsystemRule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *chart.rules(),
            *artifacts.rules(),
            *config_files.rules(),
            *fetch.rules(),
            *external_tool.rules(),
            *install_rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            *sources.rules(),
            get_chart_via_deployment,
            SubsystemRule(HelmSubsystem),
            QueryRule(InstallProcesses, [InstallHelmDeploymentFieldSet]),
            QueryRule(HelmBinary, []),
        ],
        target_types=[HelmChartTarget, HelmDeploymentTarget],
    )
    return rule_runner


def test_run_helm_install(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/chart/BUILD": """helm_chart(registries=["oci://www.example.com/external"])""",
            "src/chart/Chart.yaml": HELM_CHART_FILE,
            "src/deployment/BUILD": "helm_deployment(name='env', dependencies=['//src/chart'], sources=['*.yaml', 'subdir/*.yml'])",
            "src/deployment/values.yaml": "",
            "src/deployment/override-values.yaml": "",
            "src/deployment/subdir/values.yml": "",
        }
    )

    source_root_patterns = ["/src/*"]
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/deployment", target_name="env"))
    field_set = InstallHelmDeploymentFieldSet.create(target)

    helm = rule_runner.request(HelmBinary, [])
    install_processes = rule_runner.request(InstallProcesses, [field_set])

    assert len(install_processes) == 1
    assert install_processes[0].process
    assert install_processes[0].process.argv == (
        helm.path,
        "upgrade",
        "env",
        "mychart",
        "--install",
        "--output",
        "table",
        "--values",
        "__values/values.yaml",
        "--values",
        "__values/subdir/values.yml",
        "--values",
        "__values/override-values.yaml",
    )
