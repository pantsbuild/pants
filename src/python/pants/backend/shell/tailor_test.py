# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.shell import tailor
from pants.backend.shell.tailor import PutativeShellTargetsRequest, classify_source_files
from pants.backend.shell.target_types import ShellLibrary, Shunit2Tests
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_classify_source_files() -> None:
    test_files = {"foo/bar/baz_test.sh", "foo/test_bar.sh", "foo/tests.sh", "tests.sh"}
    lib_files = {"foo/bar/baz.sh", "foo/bar_baz.sh"}
    assert {Shunit2Tests: test_files, ShellLibrary: lib_files} == classify_source_files(
        test_files | lib_files
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, [PutativeShellTargetsRequest, AllOwnedSources]),
        ],
        target_types=[],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"src/sh/foo/{fp}": ""
            for fp in (
                "f.sh",
                "bar/baz1.sh",
                "bar/baz1_test.sh",
                "bar/baz2.sh",
                "bar/baz2_test.sh",
                "bar/baz3.sh",
            )
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeShellTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(["src/sh/foo/bar/baz1.sh", "src/sh/foo/bar/baz1_test.sh"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    ShellLibrary, path="src/sh/foo", name="lib", triggering_sources=["f.sh"]
                ),
                PutativeTarget.for_target_type(
                    ShellLibrary,
                    path="src/sh/foo/bar",
                    name="lib",
                    triggering_sources=["baz2.sh", "baz3.sh"],
                ),
                PutativeTarget.for_target_type(
                    Shunit2Tests,
                    path="src/sh/foo/bar",
                    name="tests",
                    triggering_sources=["baz2_test.sh"],
                ),
            ]
        )
        == pts
    )


def test_find_putative_targets_subset(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"src/sh/foo/{fp}": ""
            for fp in (
                "bar/bar.sh",
                "bar/bar_test.sh",
                "baz/baz.sh",
                "baz/baz_test.sh",
                "qux/qux.sh",
            )
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeShellTargetsRequest(
                PutativeTargetsSearchPaths(("src/sh/foo/bar", "src/sh/foo/qux"))
            ),
            AllOwnedSources(["src/sh/foo/bar/bar.sh"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    Shunit2Tests,
                    path="src/sh/foo/bar",
                    name="tests",
                    triggering_sources=["bar_test.sh"],
                ),
                PutativeTarget.for_target_type(
                    ShellLibrary, path="src/sh/foo/qux", name="lib", triggering_sources=["qux.sh"]
                ),
            ]
        )
        == pts
    )
