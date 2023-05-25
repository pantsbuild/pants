# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest

from pants.backend.experimental.openapi.register import rules as target_types_rules
from pants.backend.javascript.subsystems import nodejs
from pants.backend.openapi.lint.spectral.rules import SpectralFieldSet, SpectralRequest
from pants.backend.openapi.lint.spectral.rules import rules as spectral_rules
from pants.backend.openapi.sample.resources import PETSTORE_SAMPLE_SPEC
from pants.backend.openapi.target_types import (
    OpenApiDocumentGeneratorTarget,
    OpenApiSourceGeneratorTarget,
)
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *spectral_rules(),
            *config_files.rules(),
            *nodejs.rules(),
            *stripped_source_files.rules(),
            *target_types_rules(),
            QueryRule(Partitions, [SpectralRequest.PartitionRequest]),
            QueryRule(LintResult, [SpectralRequest.Batch]),
        ],
        target_types=[OpenApiDocumentGeneratorTarget, OpenApiSourceGeneratorTarget],
    )


GOOD_FILE = """
openapi: 3.0.0
info:
  title: Example
  version: 1.0.0
paths: {}
"""

BAD_FILE = PETSTORE_SAMPLE_SPEC


def run_spectral(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.experimental.openapi.lint.spectral",
            *(extra_args or ()),
        ],
        env_inherit={"PATH"},
    )
    partitions = rule_runner.request(
        Partitions[SpectralFieldSet, Any],
        [SpectralRequest.PartitionRequest(tuple(SpectralFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [SpectralRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: RuleRunner,
    target: Target,
    *,
    extra_args: list[str] | None = None,
) -> None:
    result = run_spectral(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert result[0].stdout == "No results with a severity of 'error' found!\n"


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": GOOD_FILE, "BUILD": "openapi_documents(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    assert_success(rule_runner, tgt)


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": BAD_FILE, "BUILD": "openapi_documents(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    result = run_spectral(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "openapi.yaml" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.yaml": GOOD_FILE,
            "bad.yaml": BAD_FILE,
            "BUILD": "openapi_documents(name='t', sources=['good.yaml', 'bad.yaml'])",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.yaml")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.yaml")),
    ]
    result = run_spectral(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": GOOD_FILE, "BUILD": "openapi_documents(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    result = run_spectral(rule_runner, [tgt], extra_args=["--spectral-args='--fail-severity=warn'"])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "openapi.yaml" in result[0].stdout


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": BAD_FILE, "BUILD": "openapi_documents(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    result = run_spectral(rule_runner, [tgt], extra_args=["--spectral-skip"])
    assert not result


def test_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "openapi.yaml": dedent(
                """\
                openapi: 3.0.0
                info:
                  title: Example
                  version: 1.0.0
                paths:
                  /example:
                    $ref: 'example.yaml'
                """
            ),
            "example.yaml": "{}",
            "BUILD": "openapi_documents(name='t')\nopenapi_sources(name='sources')",
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    assert_success(
        rule_runner,
        tgt,
    )
