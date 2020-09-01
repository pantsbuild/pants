# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.engine.rules import QueryRule, SubsystemRule
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE, Scope, ScopedOptions
from pants.python.python_setup import PythonSetup
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[SubsystemRule(PythonSetup), QueryRule(ScopedOptions, (Scope, OptionsBootstrapper))]
    )


def test_options_parse_scoped(rule_runner: RuleRunner) -> None:
    options_bootstrapper = create_options_bootstrapper(
        args=["-ldebug"], env=dict(PANTS_PANTSD="True", PANTS_BUILD_IGNORE='["ignoreme/"]')
    )
    global_options = rule_runner.request_product(
        ScopedOptions, [Scope(GLOBAL_SCOPE), options_bootstrapper]
    )
    python_setup_options = rule_runner.request_product(
        ScopedOptions, [Scope("python-setup"), options_bootstrapper]
    )

    assert global_options.options.level == LogLevel.DEBUG
    assert global_options.options.pantsd is True
    assert global_options.options.build_ignore == ["ignoreme/"]
    assert python_setup_options.options.platforms == ["current"]


def test_options_parse_memoization(rule_runner: RuleRunner) -> None:
    # Confirm that re-executing with a new-but-identical Options object results in memoization.

    def parse(ob):
        return rule_runner.request_product(ScopedOptions, [Scope(GLOBAL_SCOPE), ob])

    # If two OptionsBootstrapper instances are not equal, memoization will definitely not kick in.
    one_opts = create_options_bootstrapper()
    two_opts = create_options_bootstrapper()
    assert one_opts == two_opts
    assert hash(one_opts) == hash(two_opts)

    # If they are equal, executing parsing on them should result in a memoized object.
    one = parse(one_opts)
    two = parse(two_opts)
    assert one == two
    assert one is one
