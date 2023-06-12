# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pants.backend.helm.goals.tailor import PutativeHelmTargetsRequest
from pants.backend.helm.goals.tailor import rules as helm_tailor_rules
from pants.backend.helm.target_types import HelmChartTarget, HelmUnitTestTestsGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.target_types import ResourcesGeneratorTarget
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *helm_tailor_rules(),
            QueryRule(PutativeTargets, (PutativeHelmTargetsRequest, AllOwnedSources)),
        ],
    )


def test_find_helm_charts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"src/owned/Chart.yaml": "", "src/foo/Chart.yaml": "", "src/bar/Chart.yml": ""}
    )

    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeHelmTargetsRequest(("src/owned", "src/foo", "src/bar")),
            AllOwnedSources(["src/owned/Chart.yaml"]),
        ],
    )

    def expected_target(path: str, triggering_source: str) -> PutativeTarget:
        return PutativeTarget.for_target_type(
            HelmChartTarget,
            name=os.path.basename(path),
            path=path,
            triggering_sources=[triggering_source],
        )

    assert putative_targets == PutativeTargets(
        [expected_target("src/foo", "Chart.yaml"), expected_target("src/bar", "Chart.yml")]
    )


def test_find_helm_unittests(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/Chart.yaml": "",
            "src/owned/tests/owned_test.yaml": "",
            "src/owned/tests/__snapshot__/owned_test.yaml.snap": "",
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": "",
            "src/foo/tests/foo_test.yaml": "",
            "src/foo/tests/__snapshot__/foo_test.yaml.snap": "",
        }
    )

    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeHelmTargetsRequest(
                (
                    "src/owned",
                    "src/foo",
                )
            ),
            AllOwnedSources(
                [
                    "src/owned/Chart.yaml",
                    "src/owned/tests/owned_test.yaml",
                    "src/owned/tests/__snapshot__/owned_test.yaml.snap",
                    "src/foo/Chart.yaml",
                ]
            ),
        ],
    )

    def expected_unittest_target(path: str, triggering_source: str) -> PutativeTarget:
        return PutativeTarget.for_target_type(
            HelmUnitTestTestsGeneratorTarget,
            name=os.path.basename(path),
            path=path,
            triggering_sources=[triggering_source],
        )

    def expected_snapshot_target(path: str, triggering_source: str) -> PutativeTarget:
        return PutativeTarget.for_target_type(
            ResourcesGeneratorTarget,
            name=os.path.basename(path),
            path=path,
            triggering_sources=[triggering_source],
            kwargs={"sources": ("*_test.yaml.snap", "*_test.yml.snap")},
        )

    assert putative_targets == PutativeTargets(
        [
            expected_unittest_target("src/foo/tests", "foo_test.yaml"),
            expected_snapshot_target("src/foo/tests/__snapshot__", "foo_test.yaml.snap"),
        ]
    )
