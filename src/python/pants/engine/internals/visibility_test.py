# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import namedtuple

import pytest

from pants.engine.internals.visibility import (
    BuildFileVisibility,
    BuildFileVisibilityParserState,
    VisibilityAction,
    VisibilityRule,
)
from pants.testutil.pytest_util import no_exception


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
def test_check_dependency(source_path: str, target_path: str, expected_action: str) -> None:
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
    assert BuildFileVisibility.check_dependency(
        source_type="dependent_target",
        source_path=source_path,
        dependencies_visibility=dependencies_visibility,
        target_type="dependency_target",
        target_path=target_path,
        dependents_visibility=dependents_visibility,
    ) == VisibilityAction(expected_action)
