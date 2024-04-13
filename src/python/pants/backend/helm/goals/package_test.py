# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

import pytest

from pants.backend.helm.goals import package
from pants.backend.helm.goals.package import BuiltHelmArtifact, HelmPackageFieldSet
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
    gen_chart_file,
)
from pants.backend.helm.util_rules import chart, sources, tool
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.rules import QueryRule
from pants.source.source_root import rules as source_root_rules
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *tool.rules(),
            *chart.rules(),
            *package.rules(),
            *source_files.rules(),
            *source_root_rules(),
            *sources.rules(),
            *target_types_rules(),
            *HelmSubsystem.rules(),
            QueryRule(BuiltPackage, [HelmPackageFieldSet]),
        ],
    )


def _assert_build_package(rule_runner: RuleRunner, *, chart_name: str, chart_version: str) -> None:
    target = rule_runner.get_target(Address(f"src/{chart_name}", target_name=chart_name))
    field_set = HelmPackageFieldSet.create(target)

    dest_dir = field_set.output_path.value_or_default(file_ending=None)
    result = rule_runner.request(BuiltPackage, [field_set])

    assert len(result.artifacts) == 1
    assert isinstance(result.artifacts[0], BuiltHelmArtifact)
    assert result.artifacts[0].relpath == os.path.join(
        dest_dir, f"{chart_name}-{chart_version}.tgz"
    )
    assert result.artifacts[0].info


def test_helm_package(rule_runner: RuleRunner) -> None:
    chart_name = "foo"
    chart_version = "0.1.0"

    rule_runner.write_files(
        {
            f"src/{chart_name}/BUILD": f"helm_chart(name='{chart_name}')",
            f"src/{chart_name}/Chart.yaml": gen_chart_file(chart_name, version=chart_version),
            f"src/{chart_name}/values.yaml": HELM_VALUES_FILE,
            f"src/{chart_name}/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            f"src/{chart_name}/templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    _assert_build_package(rule_runner, chart_name=chart_name, chart_version=chart_version)


def test_helm_package_with_custom_output_path(rule_runner: RuleRunner) -> None:
    chart_name = "bar"
    chart_version = "0.2.0"

    output_path = "charts"

    rule_runner.write_files(
        {
            f"src/{chart_name}/BUILD": f"""helm_chart(name="{chart_name}", output_path="{output_path}")""",
            f"src/{chart_name}/Chart.yaml": gen_chart_file(chart_name, version=chart_version),
            f"src/{chart_name}/values.yaml": HELM_VALUES_FILE,
            f"src/{chart_name}/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            f"src/{chart_name}/templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    _assert_build_package(rule_runner, chart_name=chart_name, chart_version=chart_version)
