# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest

from pants.backend.visibility.rule_types import VisibilityRule, VisibilityRuleSet, flatten
from pants.engine.internals.target_adaptor import TargetAdaptor


@pytest.mark.parametrize(
    "expected, xs",
    [
        (
            ["foo"],
            "foo",
        ),
        (
            ["foo", "bar"],
            ("foo", "bar"),
        ),
        (
            ["foo", "bar", "baz"],
            (
                "foo",
                (
                    "bar",
                    ("baz",),
                ),
            ),
        ),
        (
            ["foo", "bar", "baz"],
            (
                "foo",
                (
                    "bar",
                    "baz",
                ),
            ),
        ),
        (
            ["foo", "bar", "baz"],
            (
                (
                    "foo",
                    "bar",
                    "baz",
                ),
            ),
        ),
    ],
)
def test_flatten(expected, xs) -> None:
    assert expected == list(flatten(xs))


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
    "expected, arg",
    [
        (
            VisibilityRuleSet(
                ("target",),
                (VisibilityRule.parse("src/*"),),
            ),
            ("target", "src/*"),
        ),
        (
            VisibilityRuleSet(
                ("files", "resources"),
                (
                    VisibilityRule.parse("src/*"),
                    VisibilityRule.parse("res/*"),
                    VisibilityRule.parse("!*"),
                ),
            ),
            (("files", "resources"), "src/*", "res/*", "!*"),
        ),
    ],
)
def test_visibility_rule_set_parse(expected: VisibilityRuleSet, arg: Any) -> None:
    rule_set = VisibilityRuleSet.parse(arg)
    assert expected == rule_set


@pytest.mark.parametrize(
    "expected, target, rule_spec",
    [
        (
            True,
            "python_sources",
            ("python_*", ""),
        ),
        (
            False,
            "shell_sources",
            ("python_*", ""),
        ),
        (
            True,
            "files",
            (("files", "resources"), ""),
        ),
        (
            True,
            "resources",
            (("files", "resources"), ""),
        ),
        (
            False,
            "resource",
            (("files", "resources"), ""),
        ),
    ],
)
def test_visibility_rule_set_match(expected: bool, target: str, rule_spec: tuple) -> None:
    assert expected == VisibilityRuleSet.parse(rule_spec).match(TargetAdaptor(target, None))
