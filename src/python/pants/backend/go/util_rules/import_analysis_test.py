# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go.util_rules import import_analysis, sdk
from pants.backend.go.util_rules.import_analysis import GoStdLibPackages, GoStdLibPackagesRequest
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import rules as fs_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *import_analysis.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(GoStdLibPackages, (GoStdLibPackagesRequest,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.mark.parametrize("with_race_detector", (False, True))
def test_stdlib_package_resolution(rule_runner: RuleRunner, with_race_detector: bool) -> None:
    std_lib_imports = rule_runner.request(
        GoStdLibPackages, [GoStdLibPackagesRequest(with_race_detector=with_race_detector)]
    )
    assert "fmt" in std_lib_imports
