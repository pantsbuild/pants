# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import namedtuple
from textwrap import dedent

import pytest

from pants.backend.experimental.visibility.register import rules
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.internals.visibility import (
    BuildFileVisibility,
    BuildFileVisibilityParserState,
    VisibilityAction,
    VisibilityActionDeniedError,
    VisibilityRule,
)
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*rules(), QueryRule(TargetAdaptor, (TargetAdaptorRequest,))],
        target_types=[GenericTarget],
    )


def test_create_default_visibility() -> None:
    visibility = BuildFileVisibility.create()
    assert visibility.default.value == "allow"
    assert visibility.all == ()
    assert len(visibility.targets) == 0


Scenario = namedtuple(
    "Scenario",
    "args, kwargs, expected_visibility, expected_error, parent_visibility",
    defaults=((), {}, {}, None, {}),
)


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            Scenario(
                expected_visibility=BuildFileVisibility.create(),
            ),
            id="default visibility",
        ),
        pytest.param(
            Scenario(
                kwargs=dict(all=("src/a", "!src/b")),
                expected_visibility=BuildFileVisibility.create(
                    all=("src/a", "!src/b"),
                ),
            ),
            id="simple visibility rules for all",
        ),
        pytest.param(
            Scenario(
                args=({"foo": ["."], "bar": ["!."]},),
                kwargs=dict(all=("src/a", "!src/b"), default="deny"),
                expected_visibility=BuildFileVisibility.create(
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
                parent_visibility=BuildFileVisibility.create(
                    default="warn",
                    all=("src/a", "!src/b"),
                    targets={"foo": (".",), "bar": ("!.",)},
                ),
                expected_visibility=BuildFileVisibility.create(
                    default="warn",
                    all=("src/a", "!src/b"),
                    targets={"bar": ("!.",)},
                ),
            ),
            id="inherit parent rules, but remove foo",
        ),
    ],
)
def test_set_visibility(scenario: Scenario) -> None:
    with (scenario.expected_error or no_exception()):
        visibility = BuildFileVisibilityParserState(
            scenario.parent_visibility or BuildFileVisibility.create(),
        )
        visibility.set_visibility("src/BUILD", *scenario.args, **scenario.kwargs)
        assert scenario.expected_visibility == visibility.get_frozen_visibility()


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
def test_check_visibility(source_path: str, target_path: str, expected_action: str) -> None:
    # Source rules.
    dependencies_visibility = BuildFileVisibility.create(
        # Rules for outgoing visibility.
        all=("tgt/ok/*", "?tgt/dubious/*", "!tgt/blocked/*"),
    )
    # Target rules.
    dependents_visibility = BuildFileVisibility.create(
        # Rules for incoming visibility.
        all=("src/ok/*", "?src/dubious/*", "!src/blocked/*"),
    )
    assert BuildFileVisibility.check_visibility(
        source_type="dependent_target",
        source_path=source_path,
        dependencies_visibility=dependencies_visibility,
        target_type="dependency_target",
        target_path=target_path,
        dependents_visibility=dependents_visibility,
    ) == VisibilityAction(expected_action)


def test_visibility_action(caplog) -> None:
    violation_msg = "Visibility violation for test"

    VisibilityAction("allow").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=None)
    caplog.clear()

    VisibilityAction("warn").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=[(logging.WARNING, violation_msg)])
    caplog.clear()

    with pytest.raises(VisibilityActionDeniedError, match=violation_msg):
        VisibilityAction("deny").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=None)


def denied():
    return engine_error(VisibilityActionDeniedError, contains="Visibility violation for test")


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
def test_dependents_visibility(
    rule_runner: RuleRunner, rules: list[str], kwargs, expect_error
) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": dedent(
                f"""\
                __dependents_visibility__({{target:{rules}}}, **{kwargs})
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
        rule_runner.request(
            TargetAdaptor,
            [
                TargetAdaptorRequest(
                    Address("src/dependency"),
                    address_of_origin=Address("src/origin"),
                    description_of_origin="test",
                )
            ],
        )


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
def test_dependencies_visibility(
    rule_runner: RuleRunner, rules: list[str], kwargs, expect_error
) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": "target()",
            "src/origin/BUILD": dedent(
                f"""\
                __dependencies_visibility__({{target:{rules}}}, **{kwargs})
                target(dependencies=["src/dependency:tgt"])
                """
            ),
        },
    )

    with expect_error or no_exception():
        rule_runner.request(
            TargetAdaptor,
            [
                TargetAdaptorRequest(
                    Address("src/dependency"),
                    address_of_origin=Address("src/origin"),
                    description_of_origin="test",
                )
            ],
        )
