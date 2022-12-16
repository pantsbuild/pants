# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.shell.goals import tailor
from pants.backend.shell.goals.tailor import PutativeShellTargetsRequest, classify_source_files
from pants.backend.shell.target_types import (
    ShellSourcesGeneratorTarget,
    Shunit2TestsGeneratorTarget,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_classify_source_files() -> None:
    test_files = {"foo/bar/baz_test.sh", "foo/test_bar.sh", "foo/tests.sh", "tests.sh"}
    sources_files = {"foo/bar/baz.sh", "foo/bar_baz.sh"}
    assert {
        Shunit2TestsGeneratorTarget: test_files,
        ShellSourcesGeneratorTarget: sources_files,
    } == classify_source_files(test_files | sources_files)


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
            PutativeShellTargetsRequest(("src/sh/foo", "src/sh/foo/bar")),
            AllOwnedSources(["src/sh/foo/bar/baz1.sh", "src/sh/foo/bar/baz1_test.sh"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    ShellSourcesGeneratorTarget,
                    path="src/sh/foo",
                    name=None,
                    triggering_sources=["f.sh"],
                ),
                PutativeTarget.for_target_type(
                    ShellSourcesGeneratorTarget,
                    path="src/sh/foo/bar",
                    name=None,
                    triggering_sources=["baz2.sh", "baz3.sh"],
                ),
                PutativeTarget.for_target_type(
                    Shunit2TestsGeneratorTarget,
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
            PutativeShellTargetsRequest(("src/sh/foo/bar", "src/sh/foo/qux")),
            AllOwnedSources(["src/sh/foo/bar/bar.sh"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    Shunit2TestsGeneratorTarget,
                    path="src/sh/foo/bar",
                    name="tests",
                    triggering_sources=["bar_test.sh"],
                ),
                PutativeTarget.for_target_type(
                    ShellSourcesGeneratorTarget,
                    path="src/sh/foo/qux",
                    name=None,
                    triggering_sources=["qux.sh"],
                ),
            ]
        )
        == pts
    )
