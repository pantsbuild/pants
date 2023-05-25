# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import namedtuple
from textwrap import dedent
from typing import Any, Iterable

import pytest

from pants.backend.cue.goals.lint import CueLintRequest, rules
from pants.backend.cue.target_types import CueFieldSet, CuePackageTarget
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import AddressInput
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *external_tool.rules(),
            *source_files.rules(),
            QueryRule(Partitions, [CueLintRequest.PartitionRequest]),
            QueryRule(LintResult, [CueLintRequest.Batch]),
        ],
        target_types=[CuePackageTarget],
    )


def run_cue(
    rule_runner: RuleRunner, addresses: Iterable[str], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    targets = [
        rule_runner.get_target(
            AddressInput.parse(address, description_of_origin="cue tests").file_to_address()
        )
        for address in addresses
    ]
    rule_runner.set_options(
        extra_args or (),
        # env_inherit={"PATH"},
    )
    partitions = rule_runner.request(
        Partitions[CueFieldSet, Any],
        [CueLintRequest.PartitionRequest(tuple(CueFieldSet.create(tgt) for tgt in targets))],
    )
    assert len(partitions) == 1
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [CueLintRequest.Batch("cue", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


ExpectedResult = namedtuple("ExpectedResult", "exit_code, stdout, stderr", defaults=("", ""))


def assert_results(results: tuple[LintResult, ...], *expected_results: ExpectedResult) -> None:
    assert len(results) == len(expected_results)
    for result, expected in zip(results, expected_results):
        assert result.exit_code == expected.exit_code
        assert result.stdout == expected.stdout
        assert result.stderr == expected.stderr


def test_simple_cue_vet(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "cue_package()",
            "src/example.cue": dedent(
                """\
                package example

                config: "value"
                """
            ),
        }
    )
    assert_results(
        run_cue(rule_runner, ["src/example.cue"]),
        ExpectedResult(0),
    )


def test_simple_cue_vet_issue(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "cue_package()",
            "src/example.cue": dedent(
                """\
                package example

                config: "value"
                config: 42
                """
            ),
        }
    )
    assert_results(
        run_cue(rule_runner, ["src/example.cue"]),
        ExpectedResult(
            1,
            stderr=(
                'config: conflicting values "value" and 42 (mismatched types string and int):\n'
                "    ./src/example.cue:3:9\n"
                "    ./src/example.cue:4:9\n"
            ),
        ),
    )
