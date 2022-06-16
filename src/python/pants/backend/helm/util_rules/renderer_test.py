# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.backend.helm.util_rules import renderer
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.renderer import FindHelmDeploymentChart
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget],
        rules=[
            *external_tool.rules(),
            *stripped_source_files.rules(),
            *renderer.rules(),
            QueryRule(HelmChart, (FindHelmDeploymentChart,)),
        ],
    )


def test_dummy(rule_runner: RuleRunner) -> None:
    pass
