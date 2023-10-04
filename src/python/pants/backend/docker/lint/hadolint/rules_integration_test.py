# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest

from pants.backend.docker.lint.hadolint.rules import HadolintFieldSet, HadolintRequest
from pants.backend.docker.lint.hadolint.rules import rules as hadolint_rules
from pants.backend.docker.rules import rules as docker_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.core.goals import package
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *docker_rules(),
            *external_tool.rules(),
            *hadolint_rules(),
            *package.rules(),
            *source_files.rules(),
            QueryRule(Partitions, [HadolintRequest.PartitionRequest]),
            QueryRule(LintResult, [HadolintRequest.Batch]),
        ],
        target_types=[DockerImageTarget],
    )


GOOD_FILE = "FROM python:3.8"
BAD_FILE = "FROM python"


def run_hadolint(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        extra_args or (),
        env_inherit={"PATH"},
    )
    partitions = rule_runner.request(
        Partitions[HadolintFieldSet, Any],
        [HadolintRequest.PartitionRequest(tuple(HadolintFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [HadolintRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_hadolint(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert not result[0].stdout
    assert not result[0].stderr


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Dockerfile": GOOD_FILE, "BUILD": "docker_image(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t"))
    assert_success(rule_runner, tgt)


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Dockerfile": BAD_FILE, "BUILD": "docker_image(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t"))
    result = run_hadolint(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Dockerfile:1 " in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Dockerfile.good": GOOD_FILE,
            "Dockerfile.bad": BAD_FILE,
            "BUILD": dedent(
                """
                docker_image(name="good", source="Dockerfile.good")
                docker_image(name="bad", source="Dockerfile.bad")
                """
            ),
        }
    )
    tgts = [
        rule_runner.get_target(
            Address("", target_name="good", relative_file_path="Dockerfile.good")
        ),
        rule_runner.get_target(Address("", target_name="bad", relative_file_path="Dockerfile.bad")),
    ]
    result = run_hadolint(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Dockerfile.good" not in result[0].stdout
    assert "Dockerfile.bad:1 " in result[0].stdout


def test_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            ".hadolint.yaml": "ignored: [DL3006, DL3061, DL3011]",
            "a/Dockerfile": BAD_FILE,
            "a/BUILD": "docker_image()",
            "b/Dockerfile": BAD_FILE,
            "b/BUILD": "docker_image()",
            "c/BUILD": "docker_image()",
            "c/Dockerfile": "EXPOSE 123456",
        }
    )
    tgts = [
        rule_runner.get_target(Address("a")),
        rule_runner.get_target(Address("b")),
    ]
    result = run_hadolint(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "a/Dockerfile" not in result[0].stdout
    assert "b/Dockerfile " not in result[0].stdout

    tgt = rule_runner.get_target(Address("c"))
    assert_success(rule_runner, tgt, extra_args=["--hadolint-config=.hadolint.yaml"])


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Dockerfile": BAD_FILE, "BUILD": "docker_image(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t"))
    assert_success(rule_runner, tgt, extra_args=["--hadolint-args=--ignore DL3006"])


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Dockerfile": BAD_FILE, "BUILD": "docker_image(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t"))
    result = run_hadolint(rule_runner, [tgt], extra_args=["--hadolint-skip"])
    assert not result
