# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.experimental.visibility.register import (
    BuildFileVisibilityRules,
    VisibilityRule,
    rules,
)
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.dep_rules import DependencyRuleAction, DependencyRuleActionDeniedError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import DependenciesRuleAction, DependenciesRuleActionRequest
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*rules(), QueryRule(DependenciesRuleAction, (DependenciesRuleActionRequest,))],
        target_types=[GenericTarget],
    )


def test_create_default_dependency_rules() -> None:
    dependency_rules = BuildFileVisibilityRules.create()
    assert dependency_rules.default.value == "allow"
    assert dependency_rules.all == ()
    assert len(dependency_rules.targets) == 0


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
def test_visibility_rule_match(expected: bool, rule: str, path: str, relpath: str) -> None:
    assert VisibilityRule.parse(rule).match(path, relpath) == expected


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
def test_check_dependency_rules(source_path: str, target_path: str, expected_action: str) -> None:
    # Source rules.
    dependencies_rules = BuildFileVisibilityRules.create(
        # Rules for outgoing dependency.
        all=("tgt/ok/*", "?tgt/dubious/*", "!tgt/blocked/*"),
    )
    # Target rules.
    dependents_rules = BuildFileVisibilityRules.create(
        # Rules for incoming dependency.
        all=("src/ok/*", "?src/dubious/*", "!src/blocked/*"),
    )
    assert BuildFileVisibilityRules.check_dependency_rules(
        source_adaptor=TargetAdaptor("dependent_target", "source"),
        source_path=source_path,
        dependencies_rules=dependencies_rules,
        target_adaptor=TargetAdaptor("dependency_target", "target"),
        target_path=target_path,
        dependents_rules=dependents_rules,
    ) == DependencyRuleAction(expected_action)


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
    with expect_error or no_exception():
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
    with expect_error or no_exception():
        rsp.execute_actions()
