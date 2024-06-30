# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import namedtuple
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.cue.goals.fix import CueFmtRequest, rules
from pants.backend.cue.target_types import CueFieldSet, CuePackageTarget
from pants.core.goals.fmt import FmtResult, Partitions
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import AddressInput
from pants.engine.fs import DigestContents
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *external_tool.rules(),
            *source_files.rules(),
            QueryRule(Partitions, [CueFmtRequest.PartitionRequest]),
            QueryRule(FmtResult, [CueFmtRequest.Batch]),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[CuePackageTarget],
    )


def run_cue(
    rule_runner: RuleRunner,
    addresses: Iterable[str],
    *,
    extra_args: list[str] | None = None,
) -> tuple[FmtResult, ...]:
    targets = [
        rule_runner.get_target(
            AddressInput.parse(address, description_of_origin="cue tests").file_to_address()
        )
        for address in addresses
    ]
    rule_runner.set_options(
        extra_args or (),
    )
    field_sets = [CueFieldSet.create(tgt) for tgt in targets]
    kwargs = {}
    partitions = rule_runner.request(
        Partitions, [CueFmtRequest.PartitionRequest(tuple(field_sets))]
    )
    input_sources = rule_runner.request(
        SourceFiles, [SourceFilesRequest(field_set.sources for field_set in field_sets)]
    )
    kwargs["snapshot"] = input_sources.snapshot
    assert len(partitions) == 1
    results = []
    for partition in partitions:
        result = rule_runner.request(
            FmtResult,
            [CueFmtRequest.Batch("cue", partition.elements, partition.metadata, **kwargs)],
        )
        assert result.tool_name == "cue"
        results.append(result)
    return tuple(results)


ExpectedResult = namedtuple("ExpectedResult", "stdout, stderr, files", defaults=("", "", ()))


def assert_results(
    rule_runner: RuleRunner,
    results: tuple[FmtResult, ...],
    *expected_results: ExpectedResult,
) -> None:
    assert len(results) == len(expected_results)
    for result, expected in zip(results, expected_results):
        assert result.stdout == expected.stdout
        assert result.stderr == expected.stderr
        for filename, contents in expected.files:
            fc = next(
                fc
                for fc in rule_runner.request(DigestContents, [result.output.digest])
                if fc.path == filename
            )
            assert fc.content.decode() == contents


def test_simple_cue_fmt(rule_runner: RuleRunner) -> None:
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
        rule_runner,
        run_cue(rule_runner, ["src/example.cue"]),
        ExpectedResult(),
    )


def test_simple_cue_fmt_issue(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "cue_package()",
            "src/example.cue": dedent(
                """\
                package example

                config:{
                config: 42
                }
                """
            ),
        }
    )
    assert_results(
        rule_runner,
        run_cue(rule_runner, ["src/example.cue"]),
        # `cue fmt` does not output anything. so we have only the formatted files to go on. :/
        ExpectedResult(
            files=[
                (
                    "src/example.cue",
                    dedent(
                        """\
                        package example

                        config: {
                        \tconfig: 42
                        }
                        """
                    ),
                )
            ]
        ),
    )
