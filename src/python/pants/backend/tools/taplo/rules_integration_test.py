# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Any

import pytest

from pants.backend.tools.taplo.rules import TaploFmtRequest
from pants.backend.tools.taplo.rules import rules as taplo_rules
from pants.core.goals.fmt import FmtResult, Partitions
from pants.core.util_rules import config_files, external_tool
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *taplo_rules(),
            *config_files.rules(),
            *external_tool.rules(),
            QueryRule(Partitions, [TaploFmtRequest.PartitionRequest]),
            QueryRule(FmtResult, [TaploFmtRequest.Batch]),
        ],
    )


GOOD_FILE = """[GLOBAL]\nbackend_packages = ["pants.backend.tools.taplo"]\n"""
BAD_FILE = """[GLOBAL]\nbackend_packages = [\n  "pants.backend.tools.taplo",\n]\n"""
NEEDS_CONFIG_FILE = """[GLOBAL]\npants_version = "2.17.0"\n"""
FIXED_NEEDS_CONFIG_FILE = """[GLOBAL]\npants_version="2.17.0"\n"""


def run_taplo(
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.tools.taplo", *(extra_args or ())],
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**"])])
    partition = rule_runner.request(
        Partitions[Any], [TaploFmtRequest.PartitionRequest(snapshot.files)]
    )[0]
    fmt_result = rule_runner.request(
        FmtResult,
        [
            TaploFmtRequest.Batch(
                "", partition.elements, partition_metadata=partition.metadata, snapshot=snapshot
            ),
        ],
    )
    return fmt_result


def test_no_changes_needed(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": GOOD_FILE, "sub/g.toml": GOOD_FILE})
    fmt_result = run_taplo(rule_runner)
    assert not fmt_result.stdout
    assert "found files total=2" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot(
        {"f.toml": GOOD_FILE, "sub/g.toml": GOOD_FILE}
    )
    assert fmt_result.did_change is False


def test_changes_needed(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": BAD_FILE, "sub/g.toml": BAD_FILE})
    fmt_result = run_taplo(rule_runner)
    assert not fmt_result.stdout
    assert "found files total=2" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot(
        {"f.toml": GOOD_FILE, "sub/g.toml": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_globs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": BAD_FILE, "g.toml": BAD_FILE})
    fmt_result = run_taplo(rule_runner, extra_args=["--taplo-glob-pattern=['f.toml', '!g.toml']"])
    assert not fmt_result.stdout
    assert "found files total=1" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot({"f.toml": GOOD_FILE})


def test_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/f.toml": NEEDS_CONFIG_FILE,
            ".taplo.toml": "[formatting]\ncompact_entries = true\n",
            "b/f.toml": NEEDS_CONFIG_FILE,
        }
    )
    fmt_result = run_taplo(rule_runner)
    assert not fmt_result.stdout
    assert "found files total=2" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot(
        {
            "a/f.toml": FIXED_NEEDS_CONFIG_FILE,
            "b/f.toml": FIXED_NEEDS_CONFIG_FILE,
        }
    )
    assert fmt_result.did_change


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": NEEDS_CONFIG_FILE})
    fmt_result = run_taplo(rule_runner, extra_args=["--taplo-args='--option=compact_entries=true'"])
    assert not fmt_result.stdout
    assert "found files total=1" in fmt_result.stderr
    assert fmt_result.output == rule_runner.make_snapshot({"f.toml": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change
