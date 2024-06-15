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


@pytest.mark.parametrize(
    "opt_tailor,opt_tailor_sources,opt_tailor_tests,expects_sources,expects_tests",
    [
        pytest.param(True, True, True, True, True, id="legacy tailor enabled"),
        pytest.param(False, True, True, False, False, id="legacy tailor disabled"),
        pytest.param(True, False, True, False, True, id="sources disabled"),
        pytest.param(True, True, False, True, False, id="tests disabled"),
    ],
)
def test_find_putative_targets(
    opt_tailor,
    opt_tailor_sources,
    opt_tailor_tests,
    expects_sources,
    expects_tests,
    rule_runner: RuleRunner,
) -> None:
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
    rule_runner.set_options(
        [
            f"--shell-setup-tailor={opt_tailor}",
            f"--shell-setup-tailor-sources={opt_tailor_sources}",
            f"--shell-setup-tailor-shunit2-tests={opt_tailor_tests}",
        ]
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeShellTargetsRequest(("src/sh/foo", "src/sh/foo/bar")),
            AllOwnedSources(["src/sh/foo/bar/baz1.sh", "src/sh/foo/bar/baz1_test.sh"]),
        ],
    )
    expected = []
    if expects_sources:
        expected.extend(
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
            ]
        )
    if expects_tests:
        expected.extend(
            [
                PutativeTarget.for_target_type(
                    Shunit2TestsGeneratorTarget,
                    path="src/sh/foo/bar",
                    name="tests",
                    triggering_sources=["baz2_test.sh"],
                ),
            ]
        )

    assert PutativeTargets(expected) == pts


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
