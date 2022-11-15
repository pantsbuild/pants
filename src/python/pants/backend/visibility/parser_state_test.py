# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.visibility.parser_state import BuildFileVisibilityRules
from pants.backend.visibility.rule_types import VisibilityRuleSet
from pants.backend.visibility.rules import rules as visibility_rules
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
        rules=[
            *visibility_rules(),
            QueryRule(DependenciesRuleAction, (DependenciesRuleActionRequest,)),
        ],
        target_types=[GenericTarget],
    )


@pytest.fixture
def dependencies_rules() -> BuildFileVisibilityRules:
    return BuildFileVisibilityRules(
        "test/BUILD",
        # Rules for outgoing dependency.
        (VisibilityRuleSet.parse(("*", ("tgt/ok/*", "?tgt/dubious/*", "!tgt/blocked/*"))),),
    )


@pytest.fixture
def dependents_rules() -> BuildFileVisibilityRules:
    return BuildFileVisibilityRules(
        "test/BUILD",
        # Rules for outgoing dependency.
        (VisibilityRuleSet.parse(("*", ("src/ok/*", "?src/dubious/*", "!src/blocked/*"))),),
    )


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
def test_check_dependency_rules(
    dependencies_rules: BuildFileVisibilityRules,
    dependents_rules: BuildFileVisibilityRules,
    source_path: str,
    target_path: str,
    expected_action: str,
) -> None:
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
    "rules, expect_error",
    [
        (["*"], None),
        (["!*"], denied()),
        (["src/origin", "!*"], None),
        (["!src/origin", "*"], denied()),
        (["!src/origin/nested", "*"], None),
        (["src/origin/nested", "!*"], denied()),
        (["!src/a", "!src/b", "!src/origin", "!src/c", "*"], denied()),
        (["!src/a", "!src/b", "!src/c", "*"], None),
        (["src/a", "src/b", "src/origin", "src/c", "!*"], None),
        (["src/a", "src/b", "src/c", "!*"], denied()),
    ],
)
def test_dependents_rules(rule_runner: RuleRunner, rules: list[str], expect_error) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": dedent(
                f"""\
                __dependents_rules__((target, {rules}))
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
    "rules, expect_error",
    [
        (["*"], None),
        (["src/dependency", "!*"], None),
        (["src/dependency/nested", "!*"], denied()),
        (["src/*", "!*"], None),
        (["!src/*", "*"], denied()),
    ],
)
def test_dependencies_rules(rule_runner: RuleRunner, rules: list[str], expect_error) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": "target()",
            "src/origin/BUILD": dedent(
                f"""\
                __dependencies_rules__((target, {rules}))
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
