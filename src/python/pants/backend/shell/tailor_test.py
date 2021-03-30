# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import tailor
from pants.backend.shell.tailor import PutativeShellTargetsRequest, classify_source_files
from pants.backend.shell.target_types import ShellLibrary, Shunit2Tests
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_classify_source_files() -> None:
    test_files = {"foo/bar/baz_test.sh", "foo/test_bar.sh", "foo/tests.sh", "tests.sh"}
    lib_files = {"foo/bar/baz.sh", "foo/bar_baz.sh"}
    assert {Shunit2Tests: test_files, ShellLibrary: lib_files} == classify_source_files(
        test_files | lib_files
    )


def test_find_putative_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, [PutativeShellTargetsRequest, AllOwnedSources]),
        ],
        target_types=[],
    )
    for path in [
        "src/sh/foo/f.sh",
        "src/sh/foo/bar/baz1.sh",
        "src/sh/foo/bar/baz1_test.sh",
        "src/sh/foo/bar/baz2.sh",
        "src/sh/foo/bar/baz2_test.sh",
        "src/sh/foo/bar/baz3.sh",
    ]:
        rule_runner.create_file(path)

    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeShellTargetsRequest(),
            AllOwnedSources(["src/sh/foo/bar/baz1.sh", "src/sh/foo/bar/baz1_test.sh"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(ShellLibrary, "src/sh/foo", "foo", ["f.sh"]),
                PutativeTarget.for_target_type(
                    ShellLibrary, "src/sh/foo/bar", "bar", ["baz2.sh", "baz3.sh"]
                ),
                PutativeTarget.for_target_type(
                    Shunit2Tests,
                    "src/sh/foo/bar",
                    "tests",
                    ["baz2_test.sh"],
                    kwargs={"name": "tests"},
                ),
            ]
        )
        == pts
    )
