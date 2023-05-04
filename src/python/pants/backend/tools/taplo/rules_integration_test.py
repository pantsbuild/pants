# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest
from pants.engine.fs import Digest, MergeDigests, DigestContents
from pants.engine.rules import Get


from pants.backend.tools.taplo.rules import TaploFmtRequest
from pants.backend.tools.taplo.rules import rules as taplo_rules
from pants.core.goals.fmt import FmtResult
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
        env_inherit={"PATH"},
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/*.toml"])])
    fmt_result = rule_runner.request(
        FmtResult,
        [
            TaploFmtRequest.Batch("", snapshot.files, partition_metadata=None, snapshot=snapshot),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": GOOD_FILE, "sub/g.toml": GOOD_FILE})
    fmt_result = run_taplo(rule_runner)
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot(
        {"f.toml": GOOD_FILE, "sub/g.toml": GOOD_FILE}
    )
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": BAD_FILE, "sub/g.toml": BAD_FILE})
    fmt_result = run_taplo(rule_runner)
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot(
        {"f.toml": GOOD_FILE, "sub/g.toml": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/f.toml": NEEDS_CONFIG_FILE,
            "a/.taplo.toml": "[formatting]\ncompact_entries = true\n",
            "b/f.toml": NEEDS_CONFIG_FILE,
        }
    )
    fmt_result = run_taplo(rule_runner)
    output = Get(DigestContents, Digest, fmt_result.output.digest)
    print(list(output[ii].content for ii in range(len(output))))
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot(
        {
            "a/f.toml": FIXED_NEEDS_CONFIG_FILE,
            "b/f.toml": FIXED_NEEDS_CONFIG_FILE,
            "a/.taplo.toml": "[formatting]\ncompact_entries=true\n",
        }
    )
    assert fmt_result.did_change is True


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": NEEDS_CONFIG_FILE})
    fmt_result = run_taplo(rule_runner, extra_args=["--option compact_entries=true"])
    assert fmt_result.stdout == "f.toml\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.toml": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True
