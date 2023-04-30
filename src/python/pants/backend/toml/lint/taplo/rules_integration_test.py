# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.toml.lint.taplo.rules import TaploFieldSet, TaploFmtRequest
from pants.backend.toml.lint.taplo.rules import rules as taplo_rules
from pants.backend.toml.target_types import TomlSourcesGeneratorTarget
from pants.backend.toml.target_types import rules as target_types_rules
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *taplo_rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *source_files.rules(),
            *target_types_rules(),
            QueryRule(FmtResult, [TaploFmtRequest.Batch]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[TomlSourcesGeneratorTarget],
    )


GOOD_FILE = """[GLOBAL]\nbackend_packages.add["pants.backend.toml"]\n"""
BAD_FILE = """[GLOBAL]\nbackend_packages.add[\n  "pants.backend.toml",\n]\n"""
NEEDS_CONFIG_FILE = """[GLOBAL]\npants_version = "2.17.0"\n"""
FIXED_NEEDS_CONFIG_FILE = """[GLOBAL]\npants_version="2.17.0"\n"""


def run_taplo(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> FmtResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.toml.lint.taplo", *(extra_args or ())],
        env_inherit={"PATH"},
    )
    field_sets = [TaploFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            TaploFmtRequest.Batch(
                "",
                input_sources.snapshot.files,
                partition_metadata=None,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": GOOD_FILE, "BUILD": "toml_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.toml"))
    fmt_result = run_taplo(rule_runner, [tgt])
    assert fmt_result.stdout == ""
    assert fmt_result.output == rule_runner.make_snapshot({"f.toml": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": BAD_FILE, "BUILD": "toml_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.toml"))
    fmt_result = run_taplo(rule_runner, [tgt])
    assert fmt_result.stdout == "f.toml\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.toml": GOOD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.toml": GOOD_FILE, "bad.toml": BAD_FILE, "BUILD": "toml_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.toml")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.toml")),
    ]
    fmt_result = run_taplo(rule_runner, tgts)
    assert "bad.toml\n" == fmt_result.stdout
    assert fmt_result.output == rule_runner.make_snapshot(
        {"good.toml": GOOD_FILE, "bad.toml": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/f.toml": NEEDS_CONFIG_FILE,
            "a/BUILD": "toml_sources()",
            "a/.taplo.toml": "[formatting]\ncompact_entries = true\n",
            "b/f.toml": NEEDS_CONFIG_FILE,
            "b/BUILD": "toml_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address("a", relative_file_path="f.toml")),
        rule_runner.get_target(Address("b", relative_file_path="f.toml")),
    ]
    fmt_result = run_taplo(rule_runner, tgts)
    assert fmt_result.stdout == "a/f.toml\n"
    assert fmt_result.output == rule_runner.make_snapshot(
        {"a/f.toml": FIXED_NEEDS_CONFIG_FILE, "b/f.toml": NEEDS_CONFIG_FILE}
    )
    assert fmt_result.did_change is True


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.toml": NEEDS_CONFIG_FILE, "BUILD": "toml_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.toml"))
    fmt_result = run_taplo(rule_runner, [tgt], extra_args=["--option compact_entries=true"])
    assert fmt_result.stdout == "f.toml\n"
    assert fmt_result.output == rule_runner.make_snapshot({"f.toml": FIXED_NEEDS_CONFIG_FILE})
    assert fmt_result.did_change is True
