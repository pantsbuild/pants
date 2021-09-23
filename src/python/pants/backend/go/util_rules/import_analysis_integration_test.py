# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.go.util_rules import import_analysis
from pants.backend.go.util_rules.import_analysis import ResolvedImportPathsForGoLangDistribution
from pants.core.util_rules import external_tool
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *import_analysis.rules(),
            QueryRule(ResolvedImportPathsForGoLangDistribution, []),
        ],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.go"])
    return rule_runner


def test_stdlib_package_resolution(rule_runner: RuleRunner) -> None:
    import_mapping = rule_runner.request(ResolvedImportPathsForGoLangDistribution, [])
    assert "fmt" in import_mapping.import_path_mapping
