# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations
from typing import Any, List

import pytest

from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.tools.yamllint.rules import PartitionMetadata, YamllintRequest
from pants.backend.tools.yamllint.rules import rules as yamllint_rules
from pants.backend.tools.yamllint.target_types import YamlSourcesGeneratorTarget, YamlSourceTarget
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot


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
        target_types=[
            YamlSourceTarget,
            YamlSourcesGeneratorTarget,
        ],
    )


GOOD_FILE = """\
this: is
valid: YAML
"""

DOCUMENT_START_CONFIG = """\
extends: default

rules:
  document-start: disable
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


def run_yamllint(rule_runner: RuleRunner, *, extra_args: list[str] | None = None) -> List[LintResult]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.tools.yamllint", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["*"])])
    partitions = rule_runner.request(Partitions[Any, PartitionMetadata], [YamllintRequest.PartitionRequest(snapshot.files)])
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [YamllintRequest.Batch("yamllint", partition.elements, partition.metadata)],
        )
        results.append(result)
    return results


def assert_success(
    rule_runner: RuleRunner, *, extra_args: list[str] | None = None
) -> None:
    result = run_yamllint(rule_runner, extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert not result[0].stdout
    assert not result[0].stderr


def assert_failure_with(
    snippet: str,
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
) -> None:
    result = run_yamllint(rule_runner, extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert snippet in result[0].stdout


def assert_warnings_with(
    snippet: str,
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
) -> None:
    result = run_yamllint(rule_runner, extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 2
    assert snippet in result[0].stdout


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
            ".yamllint.yaml": DOCUMENT_START_CONFIG,
            "not_yaml": NOT_YAML,
        }
    )
    assert_success(rule_runner)


def test_config_autodiscovery_yml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test.yaml": GOOD_FILE,
            ".yamllint.yml": DOCUMENT_START_CONFIG,
            "not_yaml": NOT_YAML,
        }
    )
    assert_success(rule_runner)


def test_explicit_config(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test.yaml": GOOD_FILE,
            "yamllint.yaml": DOCUMENT_START_CONFIG,
            "not_yaml": NOT_YAML,
        }
    )
    assert_success(
        rule_runner, extra_args=["--yamllint-config=yamllint.yaml", '--yamllint-args="-s"']
    )
    assert_warnings_with("missing document start", rule_runner, extra_args=['--yamllint-args="-s"'])


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.yaml": GOOD_FILE_WITH_START,
            "bad.yaml": REPEATED_KEY,
            "not_yaml": NOT_YAML,
        }
    )
    assert_failure_with(
        'bad.yaml\n  4:1       error    duplication of key "this" in mapping', rule_runner
    )
