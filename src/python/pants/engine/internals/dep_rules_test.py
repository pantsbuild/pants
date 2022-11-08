# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import namedtuple
from textwrap import dedent

import pytest

from pants.backend.experimental.visibility.register import rules
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
    DependencyRule,
    DependencyRuleAction,
    DependencyRuleActionDeniedError,
)
from pants.engine.target import DependenciesRuleAction, DependenciesRuleActionRequest
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*rules(), QueryRule(DependenciesRuleAction, (DependenciesRuleActionRequest,))],
        target_types=[GenericTarget],
    )


def test_create_default_dependency_rules() -> None:
    dependency_rules = BuildFileDependencyRules.create()
    assert dependency_rules.default.value == "allow"
    assert dependency_rules.all == ()
    assert len(dependency_rules.targets) == 0


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
                expected_dependency_rules=BuildFileDependencyRules.create(),
            ),
            id="default dependency rules",
        ),
        pytest.param(
            Scenario(
                kwargs=dict(all=("src/a", "!src/b")),
                expected_dependency_rules=BuildFileDependencyRules.create(
                    all=("src/a", "!src/b"),
                ),
            ),
            id="simple dependency rules for all",
        ),
        pytest.param(
            Scenario(
                args=({"foo": ["."], "bar": ["!."]},),
                kwargs=dict(all=("src/a", "!src/b"), default="deny"),
                expected_dependency_rules=BuildFileDependencyRules.create(
                    default="deny",
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
                parent_dependency_rules=BuildFileDependencyRules.create(
                    default="warn",
                    all=("src/a", "!src/b"),
                    targets={"foo": (".",), "bar": ("!.",)},
                ),
                expected_dependency_rules=BuildFileDependencyRules.create(
                    default="warn",
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
        )
        dependency_rules.set_dependency_rules("src/BUILD", *scenario.args, **scenario.kwargs)
        assert scenario.expected_dependency_rules == dependency_rules.get_frozen_dependency_rules()


@pytest.mark.parametrize(
    "expected, rule, path, relpath",
    [
        (True, "src/a", "src/a", ""),
        (True, "?src/a", "src/a", ""),
        (True, "!src/a", "src/a", ""),
        (False, "src/a", "src/b", ""),
        (False, "?src/a", "src/b", ""),
        (False, "!src/a", "src/b", ""),
        (True, "src/a/*", "src/a/b", ""),
        (True, "src/a/*", "src/a/b/c/d", ""),
        (False, "src/a/*/c", "src/a/b/c/d", ""),
        (True, "src/a/*/c", "src/a/b/d/c", ""),
        (True, ".", "src/a", "src/a"),
        (False, ".", "src/a", "src/b"),
        (False, ".", "src/a/b", "src/a"),
        (True, "./*", "src/a/b", "src/a"),
        (False, "./*", "src/a/b", "src/a/b/c"),
    ],
)
def test_dependency_rule_match(expected: bool, rule: str, path: str, relpath: str) -> None:
    assert DependencyRule.parse(rule).match(path, relpath) == expected


@pytest.mark.parametrize(
    "source_path, target_path, expected_action",
    [
        ("src/ok/a", "tgt/ok/b", "allow"),
        ("src/ok/a", "tgt/dubious/b", "warn"),
        ("src/ok/a", "tgt/blocked/b", "deny"),
        ("src/dubious/a", "tgt/ok/b", "warn"),
        ("src/dubious/a", "tgt/dubious/b", "warn"),
        ("src/dubious/a", "tgt/blocked/b", "deny"),
        ("src/blocked/a", "tgt/ok/b", "deny"),
        ("src/blocked/a", "tgt/dubious/b", "deny"),
        ("src/blocked/a", "tgt/blocked/b", "deny"),
    ],
)
def test_check_dependency_ruless(source_path: str, target_path: str, expected_action: str) -> None:
    # Source rules.
    dependencies_rules = BuildFileDependencyRules.create(
        # Rules for outgoing dependency.
        all=("tgt/ok/*", "?tgt/dubious/*", "!tgt/blocked/*"),
    )
    # Target rules.
    dependents_rules = BuildFileDependencyRules.create(
        # Rules for incoming dependency.
        all=("src/ok/*", "?src/dubious/*", "!src/blocked/*"),
    )
    assert BuildFileDependencyRules.check_dependency_rules(
        source_type="dependent_target",
        source_path=source_path,
        dependencies_rules=dependencies_rules,
        target_type="dependency_target",
        target_path=target_path,
        dependents_rules=dependents_rules,
    ) == DependencyRuleAction(expected_action)


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


def denied():
    return pytest.raises(
        DependencyRuleActionDeniedError,
        match="Dependency rule violation for src/origin:origin on src/dependency:dependency",
    )


@pytest.mark.parametrize(
    "rules, kwargs, expect_error",
    [
        ([], {}, None),
        ([], dict(default="deny"), denied()),
        (["src/origin"], dict(default="deny"), None),
        (["!src/origin"], dict(default="allow"), denied()),
        (["!src/origin/nested"], dict(default="allow"), None),
        (["src/origin/nested"], dict(default="deny"), denied()),
        (["!src/a", "!src/b", "!src/origin", "!src/c"], dict(default="allow"), denied()),
        (["!src/a", "!src/b", "!src/c"], dict(default="allow"), None),
        (["src/a", "src/b", "src/origin", "src/c"], dict(default="deny"), None),
        (["src/a", "src/b", "src/c"], dict(default="deny"), denied()),
    ],
)
def test_dependents_rules(rule_runner: RuleRunner, rules: list[str], kwargs, expect_error) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": dedent(
                f"""\
                __dependents_rules__({{target:{rules}}}, **{kwargs})
                target()
                """
            ),
            "src/origin/BUILD": dedent(
                """\
                target(dependencies=["src/dependency:tgt"])
                """
            ),
        },
    )

    with expect_error or no_exception():
        rsp = rule_runner.request(
            DependenciesRuleAction,
            [
                DependenciesRuleActionRequest(
                    Address("src/origin"),
                    dependencies=Addresses([Address("src/dependency")]),
                    description_of_origin="test",
                )
            ],
        )
        rsp.execute_actions()


@pytest.mark.parametrize(
    "rules, kwargs, expect_error",
    [
        ([], {}, None),
        (["src/dependency"], dict(default="deny"), None),
        (["src/dependency/nested"], dict(default="deny"), denied()),
        (["src/*"], dict(default="deny"), None),
        (["!src/*"], dict(default="allow"), denied()),
    ],
)
def test_dependencies_rules(
    rule_runner: RuleRunner, rules: list[str], kwargs, expect_error
) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": "target()",
            "src/origin/BUILD": dedent(
                f"""\
                __dependencies_rules__({{target:{rules}}}, **{kwargs})
                target(dependencies=["src/dependency:tgt"])
                """
            ),
        },
    )

    with expect_error or no_exception():
        rsp = rule_runner.request(
            DependenciesRuleAction,
            [
                DependenciesRuleActionRequest(
                    Address("src/origin"),
                    dependencies=Addresses([Address("src/dependency")]),
                    description_of_origin="test",
                )
            ],
        )
        print(rsp)
        rsp.execute_actions()
