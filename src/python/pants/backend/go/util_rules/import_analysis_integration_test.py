# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go.util_rules import import_analysis, sdk
from pants.backend.go.util_rules.import_analysis import GoStdLibImports
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *import_analysis.rules(),
            QueryRule(GoStdLibImports, []),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_stdlib_package_resolution(rule_runner: RuleRunner) -> None:
    std_lib_imports = rule_runner.request(GoStdLibImports, [])
    assert "fmt" in std_lib_imports
