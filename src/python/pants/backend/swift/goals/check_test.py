# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.swift.goals import check
from pants.backend.swift.goals.check import SwiftCheckRequest
from pants.backend.swift.subsystems import toolchain
from pants.backend.swift.target_types import SwiftFieldSet, SwiftSourcesGeneratorTarget
from pants.backend.swift.util_rules import compile
from pants.core.goals.check import CheckResult, CheckResults
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *source_files.rules(),
            *check.rules(),
            *compile.rules(),
            *toolchain.rules(),
            QueryRule(CheckResults, [SwiftCheckRequest]),
        ],
        target_types=[SwiftSourcesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


STANDALONE_FILE = dedent(
    """\
    func sayHello() -> Void {
        print("Hello, World!")
    }
    """
)

MODULE_DEPENDENT_FILE = dedent(
    """\
    sayHello()
    """
)

FAILING_FILE = dedent(
    """\
    doesntExist("Oh no...")
    """
)


def run_typecheck(
    rule_runner: RuleRunner,
    targets: Iterable[Target],
) -> tuple[CheckResult, ...]:
    field_sets = [SwiftFieldSet.create(tgt) for tgt in targets]
    check_results = rule_runner.request(CheckResults, [SwiftCheckRequest(field_sets)])
    return check_results.results


def test_success_on_single_module(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "main.swift": MODULE_DEPENDENT_FILE,
            "talker.swift": STANDALONE_FILE,
            "BUILD": "swift_sources(name='t')",
        }
    )
    tgts = (
        rule_runner.get_target(
            Address("", target_name="t", relative_file_path="main.swift"),
        ),
    )
    check_results = run_typecheck(
        rule_runner,
        tgts,
    )
    assert len(check_results) == 1
    assert check_results[0].exit_code == 0


def test_success_multiple_modules(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Module1/main.swift": MODULE_DEPENDENT_FILE,
            "Module1/talker.swift": STANDALONE_FILE,
            "Module1/BUILD": "swift_sources(name='t1')",
            "Module2/main.swift": STANDALONE_FILE,
            "Module2/BUILD": "swift_sources(name='t2')",
        }
    )
    tgts = (
        rule_runner.get_target(
            Address("Module1", target_name="t1", relative_file_path="main.swift"),
        ),
        rule_runner.get_target(
            Address("Module2", target_name="t2", relative_file_path="main.swift"),
        ),
    )
    check_results = run_typecheck(
        rule_runner,
        tgts,
    )
    assert len(check_results) == 2
    for check_result in check_results:
        assert check_result.exit_code == 0


def test_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "main.swift": FAILING_FILE,
            "BUILD": "swift_sources(name='t')",
        }
    )
    tgts = (
        rule_runner.get_target(
            Address("", target_name="t", relative_file_path="main.swift"),
        ),
    )
    check_results = run_typecheck(
        rule_runner,
        tgts,
    )
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "error: cannot find" in check_results[0].stderr
