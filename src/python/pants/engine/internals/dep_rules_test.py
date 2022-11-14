# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import namedtuple
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable, Mapping, Tuple, cast

import pytest

from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
    DependencyRule,
    DependencyRuleAction,
    DependencyRuleActionDeniedError,
    DependencyRules,
)
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.util.frozendict import FrozenDict

# -----------------------------------------------------------------------------------------------
# This section demonstrates an example dependecy rules implementation, used in the tests in this
# module.
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DummyTestRule(DependencyRule):
    action: DependencyRuleAction
    pattern: str

    @classmethod
    def parse(cls, rule: str) -> DummyTestRule:
        if rule.startswith("!"):
            action = DependencyRuleAction.DENY
            pattern = rule[1:]
        elif rule.startswith("?"):
            action = DependencyRuleAction.WARN
            pattern = rule[1:]
        else:
            action = DependencyRuleAction.ALLOW
            pattern = rule
        return cls(action, pattern)

    def match(self, path: str, relpath: str) -> bool:
        pattern = relpath if self.pattern == "." else self.pattern
        if pattern.startswith("./"):
            pattern = relpath + pattern[1:]
        return fnmatch(path, pattern)


DummyTestRules = Tuple[DummyTestRule, ...]


@dataclass(frozen=True)
class DummyBuildFileTestRules(BuildFileDependencyRules):
    default: DependencyRuleAction
    all: DependencyRules
    targets: Mapping[str, DependencyRules]

    @classmethod
    def create(
        cls,
        default: DependencyRuleAction = DependencyRuleAction.ALLOW,
        all: Iterable[str | DependencyRule] = (),
        targets: Mapping[str, Iterable[str | DependencyRule]] = {},
    ) -> DummyBuildFileTestRules:
        return cls(
            default,
            cls.parse_dummy_rules(all),
            FrozenDict(
                {type_alias: cls.parse_dummy_rules(rules) for type_alias, rules in targets.items()}
            ),
        )

    @classmethod
    def parse_dummy_rules(cls, rules: Iterable[str | DependencyRule]) -> DependencyRules:
        return tuple(DummyTestRule.parse(rule) if isinstance(rule, str) else rule for rule in rules)

    def get_rules(self, type_alias: str) -> DummyTestRules:
        if type_alias in self.targets:
            return cast(DummyTestRules, self.targets[type_alias])
        else:
            return cast(DummyTestRules, self.all)

    def get_action(self, type_alias: str, path: str, relpath: str) -> DependencyRuleAction:
        """Get applicable rule for target type from `path`.

        The rules are declared in `relpath`.
        """
        for dummy_rule in self.get_rules(type_alias):
            if dummy_rule.match(path, relpath):
                return dummy_rule.action
        return self.default

    @staticmethod
    def check_dependency_rules(
        *,
        source_type: str,
        source_path: str,
        dependencies_rules: BuildFileDependencyRules | None,
        target_type: str,
        target_path: str,
        dependents_rules: BuildFileDependencyRules | None,
    ) -> DependencyRuleAction:
        # Check outgoing dependency action
        outgoing = (
            cast(DummyBuildFileTestRules, dependencies_rules).get_action(
                source_type, target_path, relpath=source_path
            )
            if dependencies_rules is not None
            else DependencyRuleAction.ALLOW
        )
        if outgoing == DependencyRuleAction.DENY:
            return outgoing
        # Check incoming dependency action
        incoming = (
            cast(DummyBuildFileTestRules, dependents_rules).get_action(
                target_type, source_path, relpath=target_path
            )
            if dependents_rules is not None
            else DependencyRuleAction.ALLOW
        )
        return incoming if incoming != DependencyRuleAction.ALLOW else outgoing


# -----------------------------------------------------------------------------------------------
# Begin tests.
# -----------------------------------------------------------------------------------------------

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
                expected_dependency_rules=DummyBuildFileTestRules.create(),
            ),
            id="default dependency rules",
        ),
        pytest.param(
            Scenario(
                kwargs=dict(all=("src/a", "!src/b")),
                expected_dependency_rules=DummyBuildFileTestRules.create(
                    all=("src/a", "!src/b"),
                ),
            ),
            id="simple dependency rules for all",
        ),
        pytest.param(
            Scenario(
                args=({"foo": ["."], "bar": ["!."]},),
                kwargs=dict(all=("src/a", "!src/b"), default="deny"),
                expected_dependency_rules=DummyBuildFileTestRules.create(
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
                parent_dependency_rules=DummyBuildFileTestRules.create(
                    default=DependencyRuleAction.WARN,
                    all=("src/a", "!src/b"),
                    targets={"foo": (".",), "bar": ("!.",)},
                ),
                expected_dependency_rules=DummyBuildFileTestRules.create(
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
            build_file_dependency_rules_class=DummyBuildFileTestRules,
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
