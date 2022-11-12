# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import namedtuple

import pytest

from pants.backend.experimental.visibility.register import BuildFileVisibilityRules
from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
    DependencyRuleAction,
    DependencyRuleActionDeniedError,
)
from pants.testutil.pytest_util import assert_logged, no_exception

Scenario = namedtuple(
    "Scenario",
    "args, kwargs, expected_dependency_rules, expected_error, parent_dependency_rules",
    defaults=((), {}, {}, None, {}),
)


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            Scenario(
                expected_dependency_rules=BuildFileVisibilityRules.create(),
            ),
            id="default dependency rules",
        ),
        pytest.param(
            Scenario(
                kwargs=dict(all=("src/a", "!src/b")),
                expected_dependency_rules=BuildFileVisibilityRules.create(
                    all=("src/a", "!src/b"),
                ),
            ),
            id="simple dependency rules for all",
        ),
        pytest.param(
            Scenario(
                args=({"foo": ["."], "bar": ["!."]},),
                kwargs=dict(all=("src/a", "!src/b"), default="deny"),
                expected_dependency_rules=BuildFileVisibilityRules.create(
                    default=DependencyRuleAction.DENY,
                    all=("src/a", "!src/b"),
                    targets={"foo": (".",), "bar": ("!.",)},
                ),
            ),
            id="target rules with default deny",
        ),
        pytest.param(
            Scenario(
                args=({"foo": []},),
                kwargs=dict(extend=True),
                parent_dependency_rules=BuildFileVisibilityRules.create(
                    default=DependencyRuleAction.WARN,
                    all=("src/a", "!src/b"),
                    targets={"foo": (".",), "bar": ("!.",)},
                ),
                expected_dependency_rules=BuildFileVisibilityRules.create(
                    default=DependencyRuleAction.WARN,
                    all=("src/a", "!src/b"),
                    targets={"bar": ("!.",)},
                ),
            ),
            id="inherit parent rules, but remove foo",
        ),
    ],
)
def test_set_dependency_rules(scenario: Scenario) -> None:
    with (scenario.expected_error or no_exception()):
        dependency_rules = BuildFileDependencyRulesParserState(
            scenario.parent_dependency_rules or BuildFileDependencyRules.create(),
            build_file_dependency_rules_class=BuildFileVisibilityRules,
        )
        dependency_rules.set_dependency_rules("src/BUILD", *scenario.args, **scenario.kwargs)
        assert scenario.expected_dependency_rules == dependency_rules.get_frozen_dependency_rules()


def test_dependency_rule_action(caplog) -> None:
    violation_msg = "Dependency rule violation for test"

    DependencyRuleAction("allow").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=None)
    caplog.clear()

    DependencyRuleAction("warn").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=[(logging.WARNING, violation_msg)])
    caplog.clear()

    with pytest.raises(DependencyRuleActionDeniedError, match=violation_msg):
        DependencyRuleAction("deny").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=None)
