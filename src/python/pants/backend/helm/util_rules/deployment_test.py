# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
from pants.backend.helm.testutil import gen_chart_file
from pants.backend.helm.util_rules import deployment
from pants.backend.helm.util_rules.chart import HelmChart
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget],
        rules=[
            *external_tool.rules(),
            *stripped_source_files.rules(),
            *deployment.rules(),
            QueryRule(HelmChart, (HelmDeploymentFieldSet,)),
        ],
    )


def test_obtain_chart_from_deployment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": gen_chart_file("foo", version="1.0.0"),
            "src/bar/BUILD": dedent(
                """\
                helm_deployment(dependencies=["//src/foo"])
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/bar"))
    field_set = HelmDeploymentFieldSet.create(target)

    chart = rule_runner.request(HelmChart, [field_set])

    assert chart.metadata.name == "foo"
    assert chart.metadata.version == "1.0.0"


def test_fail_when_no_chart_dependency_is_found(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": """helm_deployment(name="foo")"""})

    target = rule_runner.get_target(Address("", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(target)

    msg = f"The target '{field_set.address}' is missing a dependency on a `helm_chart` target."
    with pytest.raises(ExecutionError, match=msg):
        rule_runner.request(HelmChart, [field_set])


def test_fail_when_more_than_one_chart_is_found(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": gen_chart_file("foo", version="1.0.0"),
            "src/bar/BUILD": "helm_chart()",
            "src/bar/Chart.yaml": gen_chart_file("bar", version="1.0.3"),
            "src/quxx/BUILD": dedent(
                """\
                helm_deployment(dependencies=["//src/foo", "//src/bar"])
                """
            ),
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])

    target = rule_runner.get_target(Address("src/quxx"))
    field_set = HelmDeploymentFieldSet.create(target)

    msg = (
        f"The target '{field_set.address}' has too many `{HelmChartTarget.alias}` "
        "addresses in its dependencies, it should have only one."
    )
    with pytest.raises(ExecutionError, match=msg):
        rule_runner.request(HelmChart, [field_set])
