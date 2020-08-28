# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

import pytest

from pants.backend.project_info import list_roots
from pants.backend.project_info.list_roots import Roots
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=list_roots.rules())


def assert_roots(
    rule_runner: RuleRunner,
    configured: List[str],
    *,
    marker_files: Optional[List[str]] = None,
    expected: Optional[List[str]] = None,
) -> None:
    result = rule_runner.run_goal_rule(
        Roots,
        args=[
            f"--source-root-patterns={configured}",
            f"--source-marker-filenames={marker_files or []}",
        ],
    )
    assert result.stdout.splitlines() == sorted(expected or configured)


def test_single_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.create_dir("fakeroot")
    assert_roots(rule_runner, ["fakeroot"])


def test_multiple_source_roots(rule_runner: RuleRunner) -> None:
    rule_runner.create_dir("fakerootA")
    rule_runner.create_dir("fakerootB")
    assert_roots(rule_runner, ["fakerootA", "fakerootB"])


def test_buildroot_is_source_root(rule_runner: RuleRunner) -> None:
    assert_roots(rule_runner, ["/"], expected=["."])


def test_marker_file(rule_runner: RuleRunner) -> None:
    rule_runner.create_file("fakerootA/SOURCE_ROOT")
    rule_runner.create_file("fakerootB/setup.py")
    assert_roots(
        rule_runner,
        configured=[],
        marker_files=["SOURCE_ROOT", "setup.py"],
        expected=["fakerootA", "fakerootB"],
    )
