# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.helm.goals.tailor import PutativeHelmChartTargetsRequest, classify_source_files
from pants.backend.helm.goals.tailor import rules as tailor_rules
from pants.backend.helm.target_types import HelmChartTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor_rules(),
            QueryRule(PutativeTargets, (PutativeHelmChartTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )


def test_classify_source_files() -> None:
    all_files = {
        "foo/bar/Chart.yaml",
        "foo/bar/templates/_helpers.tpl",
        "foo/bar/templates/service.yaml",
        "other_file.yaml",
    }

    expected_classification = {
        HelmChartTarget: {
            "foo/bar/Chart.yaml",
        },
    }
    assert classify_source_files(all_files) == expected_classification


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/bar/Chart.yaml": "",
            "foo/bar/templates/_helpers.tpl": "",
            "foo/bar/templates/service.yaml": "",
            "foo/quxx/Chart.yaml": "",
            "foo/quxx/values.yaml": "",
        }
    )

    expected_targets = PutativeTargets(
        [
            PutativeTarget.for_target_type(
                HelmChartTarget, path="foo/bar", name=None, triggering_sources=["Chart.yaml"]
            ),
            PutativeTarget.for_target_type(
                HelmChartTarget, path="foo/quxx", name=None, triggering_sources=["Chart.yaml"]
            ),
        ]
    )

    found_targets = rule_runner.request(
        PutativeTargets,
        [PutativeHelmChartTargetsRequest(PutativeTargetsSearchPaths(("",))), AllOwnedSources([])],
    )
    assert found_targets == expected_targets
