# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.subsystems.repos import PythonRepos
from pants.option.scope import GLOBAL_SCOPE, Scope, ScopedOptions
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.logging import LogLevel


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[*PythonRepos.rules(), QueryRule(ScopedOptions, (Scope,))])


def test_options_parse_scoped(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["-ldebug"], env=dict(PANTS_PANTSD="True", PANTS_BUILD_IGNORE='["ignoreme/"]')
    )
    global_options = rule_runner.request(ScopedOptions, [Scope(GLOBAL_SCOPE)])
    python_repos_options = rule_runner.request(ScopedOptions, [Scope("python-repos")])

    assert global_options.options.level == LogLevel.DEBUG
    assert global_options.options.pantsd is True
    assert global_options.options.build_ignore == ["ignoreme/"]
    assert python_repos_options.options.indexes == ["https://pypi.org/simple/"]


def test_options_parse_memoization(rule_runner: RuleRunner) -> None:
    # Confirm that re-executing with a new-but-identical Options object results in memoization.

    def parse() -> ScopedOptions:
        # This will create a new `OptionsBootstrapper` and set it as a `SessionValue` on the engine
        # session.
        rule_runner.set_options([])
        return rule_runner.request(ScopedOptions, [Scope(GLOBAL_SCOPE)])

    # If they are equal, executing parsing on them should result in a memoized object.
    one = parse()
    two = parse()
    assert one == two
    assert one is one
