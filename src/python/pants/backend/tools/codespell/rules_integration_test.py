# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest

from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.tools.codespell.rules import CodespellRequest, PartitionInfo
from pants.backend.tools.codespell.rules import rules as codespell_rules
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *codespell_rules(),
            *config_files.rules(),
            *source_files.rules(),
            *external_tool.rules(),
            *pex_rules(),
            QueryRule(Partitions, [CodespellRequest.PartitionRequest]),
            QueryRule(LintResult, [CodespellRequest.Batch]),
        ],
    )


GOOD_FILE = """\
This file has correct spelling.
No errors here.
"""

BAD_FILE = """\
This file has a speling error.
And also a teh typo.
"""

CONFIG_FILE = """\
[codespell]
ignore-words-list = speling
"""

PYPROJECT_TOML_CONFIG = """\
[tool.codespell]
ignore-words-list = "speling"
"""

SETUP_CFG_CONFIG = """\
[codespell]
ignore-words-list = speling
"""


def run_codespell(
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
) -> LintResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.tools.codespell", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**"])])
    partitions = rule_runner.request(
        Partitions[Any, PartitionInfo], [CodespellRequest.PartitionRequest(snapshot.files)]
    )
    assert len(partitions) >= 1
    # Run on all partitions and return the first non-zero result, or the last result
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [CodespellRequest.Batch("", partition.elements, partition_metadata=partition.metadata)],
        )
        results.append(result)
        if result.exit_code != 0:
            return result
    return results[-1] if results else results[0]


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.txt": GOOD_FILE})
    result = run_codespell(rule_runner)
    assert result.exit_code == 0


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.txt": BAD_FILE})
    result = run_codespell(rule_runner)
    assert result.exit_code == 65
    assert "speling" in result.stdout or "speling" in result.stderr
    assert "teh" in result.stdout or "teh" in result.stderr


def test_config_file_discovery(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test.txt": BAD_FILE,
            ".codespellrc": CONFIG_FILE,
        }
    )
    result = run_codespell(rule_runner)
    # Should still fail because "teh" is not ignored, but "speling" is
    assert result.exit_code == 65
    # "speling" should not appear in output since it's ignored
    output = result.stdout + result.stderr
    assert "teh" in output


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.txt": BAD_FILE})
    # When skipped, partitions should be empty
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.tools.codespell", "--codespell-skip"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**"])])
    partitions = rule_runner.request(
        Partitions[Any, PartitionInfo], [CodespellRequest.PartitionRequest(snapshot.files)]
    )
    assert len(partitions) == 0


def test_extra_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"test.txt": BAD_FILE})
    result = run_codespell(
        rule_runner, extra_args=["--codespell-args='--ignore-words-list=speling,teh'"]
    )
    assert result.exit_code == 0


def test_file_exclusion(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "good.txt": GOOD_FILE,
            "bad.txt": BAD_FILE,
        }
    )
    # First verify that without exclusion, bad.txt is caught
    result = run_codespell(rule_runner)
    assert result.exit_code == 65
    output = result.stdout + result.stderr
    assert "bad.txt" in output

    # Now verify that with exclusion, bad.txt is not checked
    result = run_codespell(rule_runner, extra_args=["--codespell-exclude=['**/bad.txt']"])
    assert result.exit_code == 0


def test_pyproject_toml_config(rule_runner: RuleRunner) -> None:
    """Test that pyproject.toml config is discovered for files without .codespellrc."""
    rule_runner.write_files(
        {
            "test.txt": BAD_FILE,
            "pyproject.toml": PYPROJECT_TOML_CONFIG,
        }
    )
    result = run_codespell(rule_runner)
    # Should still fail because "teh" is not ignored, but "speling" is
    assert result.exit_code == 65
    output = result.stdout + result.stderr
    assert "test.txt" in output and "teh" in output
    # "speling" in test.txt should not appear since it's ignored by pyproject.toml config
    # (note: pyproject.toml itself may report "speling" since it's being scanned too)
    assert "test.txt:1: speling" not in output


def test_setup_cfg_config(rule_runner: RuleRunner) -> None:
    """Test that setup.cfg config is discovered for files without .codespellrc."""
    rule_runner.write_files(
        {
            "test.txt": BAD_FILE,
            "setup.cfg": SETUP_CFG_CONFIG,
        }
    )
    result = run_codespell(rule_runner)
    # Should still fail because "teh" is not ignored, but "speling" is
    assert result.exit_code == 65
    output = result.stdout + result.stderr
    assert "test.txt" in output and "teh" in output
    # "speling" in test.txt should not appear since it's ignored by setup.cfg config
    # (note: setup.cfg itself may report "speling" since it's being scanned too)
    assert "test.txt:1: speling" not in output


def test_multiple_config_partitions(rule_runner: RuleRunner) -> None:
    """Test that files are correctly partitioned by their nearest config file."""
    rule_runner.write_files(
        {
            "src/good.txt": GOOD_FILE,
            "src/.codespellrc": CONFIG_FILE,  # Ignores "speling"
            "tests/bad.txt": BAD_FILE,
            # tests/ has no config, so both "speling" and "teh" should be caught
        }
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.tools.codespell"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**"])])
    partitions = rule_runner.request(
        Partitions[Any, PartitionInfo], [CodespellRequest.PartitionRequest(snapshot.files)]
    )

    # Should have 2 partitions: one for src/ (with config) and one for tests/ (without)
    assert len(partitions) == 2

    # Find the partition with the config
    config_partition = None
    default_partition = None
    for p in partitions:
        if p.metadata.config_snapshot is not None:
            config_partition = p
        else:
            default_partition = p

    assert config_partition is not None
    assert default_partition is not None
    assert "src/good.txt" in config_partition.elements
    assert "tests/bad.txt" in default_partition.elements
