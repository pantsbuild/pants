# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pants.backend.helm.goals.tailor import PutativeHelmChartTargetsRequest
from pants.backend.helm.goals.tailor import rules as helm_tailor_rules
from pants.backend.helm.target_types import HelmChartTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *helm_tailor_rules(),
            QueryRule(PutativeTargets, (PutativeHelmChartTargetsRequest, AllOwnedSources)),
        ],
    )


def test_find_helm_charts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"src/owned/Chart.yaml": "", "src/foo/Chart.yaml": "", "src/bar/Chart.yml": ""}
    )

    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeHelmChartTargetsRequest(("src/owned", "src/foo", "src/bar")),
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
