# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, overload

import pytest

from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.tools.yamllint.rules import PartitionInfo, YamllintRequest
from pants.backend.tools.yamllint.rules import rules as yamllint_rules
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *yamllint_rules(),
            *config_files.rules(),
            *source_files.rules(),
            *external_tool.rules(),
            *pex_rules(),
            QueryRule(Partitions, [YamllintRequest.PartitionRequest]),
            QueryRule(LintResult, [YamllintRequest.Batch]),
        ],
    )


GOOD_FILE = """\
this: is
valid: YAML
"""

DOCUMENT_START_DISABLE_CONFIG = """\
extends: default

rules:
  document-start: disable
"""

RELAXED_CONFIG = """
extends: relaxed
"""

GOOD_FILE_WITH_START = """\
---
this: is
valid: YAML
"""

REPEATED_KEY = """\
---
this: key
is: repeated
this: here
"""

NOT_YAML = """\
This definitely
isn't valid YAML,
is it?
"""


@overload
def run_yamllint(
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
    expected_partitions: None = None,
) -> LintResult: ...


@overload
def run_yamllint(
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
    expected_partitions: tuple[tuple[str, ...], dict[str, tuple[str, ...]]],
) -> list[LintResult]: ...


def run_yamllint(
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
    expected_partitions: tuple[tuple[str, ...], dict[str, tuple[str, ...]]] | None = None,
) -> LintResult | list[LintResult]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.tools.experimental.yamllint", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**"])])
    partitions = rule_runner.request(
        Partitions[Any, PartitionInfo], [YamllintRequest.PartitionRequest(snapshot.files)]
    )

    if expected_partitions:
        expected_default_partition = expected_partitions[0]
        default_partitions = tuple(p for p in partitions if p.metadata.config_snapshot is None)
        if expected_default_partition:
            assert len(default_partitions) == 1
            assert default_partitions[0].elements == expected_default_partition
        else:
            assert len(default_partitions) == 0

        config_partitions = tuple(p for p in partitions if p.metadata.config_snapshot)
        expected_config_partitions = expected_partitions[1]
        assert len(config_partitions) == len(expected_config_partitions)
        for partition in config_partitions:
            assert partition.metadata.config_snapshot is not None
            config_file = partition.metadata.config_snapshot.files[0]

            assert config_file in expected_config_partitions
            assert partition.elements == expected_config_partitions[config_file]
    else:
        assert len(partitions) == 1

    results = [
        rule_runner.request(
            LintResult,
            [
                YamllintRequest.Batch(
                    "",
                    partition.elements,
                    partition_metadata=partition.metadata,
                )
            ],
        )
        for partition in partitions
    ]
    return results if expected_partitions else results[0]


def assert_success(rule_runner: RuleRunner, *, extra_args: list[str] | None = None) -> None:
    result = run_yamllint(rule_runner, extra_args=extra_args)
    assert result.exit_code == 0
    assert not result.stdout
    assert not result.stderr


def assert_failure_with(
    snippet: str,
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
) -> None:
    result = run_yamllint(rule_runner, extra_args=extra_args)
    assert result.exit_code == 1
    assert snippet in result.stdout


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.yaml": GOOD_FILE_WITH_START, "not_yaml": NOT_YAML})
    assert_success(rule_runner)


def test_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.yaml": REPEATED_KEY, "not_yaml": NOT_YAML})
    assert_failure_with('duplication of key "this"', rule_runner)


def test_config_autodiscovery(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test.yaml": GOOD_FILE,
            ".yamllint": DOCUMENT_START_DISABLE_CONFIG,
            "not_yaml": NOT_YAML,
        }
    )
    assert_success(rule_runner)


def test_config_autodiscovery_yml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test.yaml": GOOD_FILE,
            ".yamllint.yml": DOCUMENT_START_DISABLE_CONFIG,
            "not_yaml": NOT_YAML,
        }
    )
    assert_success(rule_runner, extra_args=["--yamllint-config-file-name=.yamllint.yml"])


def test_multi_config(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test.yaml": GOOD_FILE_WITH_START,
            "subdir1/.yamllint": DOCUMENT_START_DISABLE_CONFIG,
            "subdir1/subdir.yaml": GOOD_FILE,
            "subdir1/nested/subdir.yaml": GOOD_FILE,
            "subdir2/.yamllint": RELAXED_CONFIG,
            "subdir2/subdir.yaml": GOOD_FILE,
            "not_yaml": NOT_YAML,
        }
    )
    results = run_yamllint(
        rule_runner,
        extra_args=["--yamllint-args=-s"],
        expected_partitions=(
            ("test.yaml",),
            {
                "subdir1/.yamllint": ("subdir1/nested/subdir.yaml", "subdir1/subdir.yaml"),
                "subdir2/.yamllint": ("subdir2/subdir.yaml",),
            },
        ),
    )
    assert len(results) == 3
    for result in results:
        assert result.exit_code == 0
        assert not result.stdout
        assert not result.stderr
