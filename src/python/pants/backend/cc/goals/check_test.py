# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

import pytest

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.goals import check
from pants.backend.cc.goals.check import CCCheckRequest
from pants.backend.cc.subsystems import toolchain
from pants.backend.cc.target_types import CCFieldSet, CCSourcesGeneratorTarget
from pants.backend.cc.util_rules import compile
from pants.core.goals.check import CheckResult, CheckResults
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *check.rules(),
            *compile.rules(),
            *dep_inf_rules(),
            *source_files.rules(),
            *toolchain.rules(),
            QueryRule(CheckResults, [CCCheckRequest]),
        ],
        target_types=[CCSourcesGeneratorTarget],
    )
    # Need to get the PATH so we can access system GCC or Clang
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


BAD_FILE = """\
    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return 0;
    }
    """

GOOD_FILE = """\
    #include <iostream>

    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return 0;
    }
    """


def run_check(
    rule_runner: RuleRunner,
    targets: Iterable[Target],
) -> tuple[CheckResult, ...]:
    field_sets = [CCFieldSet.create(tgt) for tgt in targets]
    check_results = rule_runner.request(CheckResults, [CCCheckRequest(field_sets)])
    return check_results.results


def test_check_pass(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": GOOD_FILE, "BUILD": "cc_sources(name='t')"})
    tgts = (rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp")),)
    check_results = run_check(
        rule_runner,
        tgts,
    )
    assert len(check_results) == 1
    assert check_results[0].exit_code == 0


def test_check_fail(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": BAD_FILE, "BUILD": "cc_sources(name='t')"})
    tgts = (rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp")),)
    check_results = run_check(
        rule_runner,
        tgts,
    )
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "error: use of undeclared identifier" in check_results[0].stderr
