# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.codegen.protobuf.lint.buf.format_rules import BufFieldSet, BufFormatRequest
from pants.backend.codegen.protobuf.lint.buf.format_rules import rules as buf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files, external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *buf_rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *source_files.rules(),
            *target_types_rules(),
            QueryRule(LintResults, [BufFormatRequest]),
            QueryRule(FmtResult, [BufFormatRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


GOOD_FILE = 'syntax = "proto3";\n\npackage foo.v1;\nmessage Foo {}\n'
BAD_FILE = 'syntax = "proto3";\n\npackage foo.v1;\nmessage Foo {\n}\n'


def run_buf(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[tuple[LintResult, ...], FmtResult]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.codegen.protobuf.lint.buf",
            *(extra_args or ()),
        ],
        env_inherit={"PATH"},
    )
    field_sets = [BufFieldSet.create(tgt) for tgt in targets]
    results = rule_runner.request(LintResults, [BufFormatRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            BufFormatRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )

    return results.results, fmt_result


def get_snapshot(rule_runner: RuleRunner, source_files: dict[str, str]) -> Snapshot:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    digest = rule_runner.request(Digest, [CreateDigest(files)])
    return rule_runner.request(Snapshot, [digest])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.proto": GOOD_FILE, "BUILD": "protobuf_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.proto"))
    lint_results, fmt_result = run_buf(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stdout == ""
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_snapshot(rule_runner, {"f.proto": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.proto": BAD_FILE, "BUILD": "protobuf_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.proto"))
    lint_results, fmt_result = run_buf(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 100
    assert "f.proto.orig" in lint_results[0].stdout
    assert fmt_result.output == get_snapshot(rule_runner, {"f.proto": GOOD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"good.proto": GOOD_FILE, "bad.proto": BAD_FILE, "BUILD": "protobuf_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.proto")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.proto")),
    ]
    lint_results, fmt_result = run_buf(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 100
    assert "bad.proto.orig" in lint_results[0].stdout
    assert "good.proto" not in lint_results[0].stdout
    assert fmt_result.output == get_snapshot(
        rule_runner, {"good.proto": GOOD_FILE, "bad.proto": GOOD_FILE}
    )
    assert fmt_result.did_change is True


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.proto": GOOD_FILE, "BUILD": "protobuf_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.proto"))
    lint_results, fmt_result = run_buf(rule_runner, [tgt], extra_args=["--buf-format-args=--debug"])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stdout == ""
    assert "DEBUG" in lint_results[0].stderr
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_snapshot(rule_runner, {"f.proto": GOOD_FILE})
    assert fmt_result.did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"f.proto": BAD_FILE, "BUILD": "protobuf_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="f.proto"))
    lint_results, fmt_result = run_buf(rule_runner, [tgt], extra_args=["--buf-format-skip"])
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
