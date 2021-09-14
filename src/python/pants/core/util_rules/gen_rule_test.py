# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.core.target_types import GenRuleTarget
from pants.core.util_rules.gen_rule import run_gen_rule
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *source_files_rules(),
            run_gen_rule,
            QueryRule(ProcessResult, [GenRuleTarget]),
        ],
        target_types=[GenRuleTarget],
    )


def assert_gen_rule_result(
    rule_runner: RuleRunner, address: Address, stdout=None, stderr=None, output_files=None
) -> None:
    target = rule_runner.get_target(address)
    result = rule_runner.request(ProcessResult, [target])
    if stdout:
        assert result.stdout == stdout
    if stderr:
        assert result.stderr == stderr
    if output_files:
        pass


def test_simple_message(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                gen_rule(
                  name="hello",
                  sources=["message.txt"],
                  command="cat message.txt",  # support $(sources) etc similar to what bazel does?
                )
                """
            ),
            "src/message.txt": "Hello gen_rule",
        }
    )

    assert_gen_rule_result(
        rule_runner,
        Address("src", target_name="hello"),
        stdout=b"Hello gen_rule",
    )
