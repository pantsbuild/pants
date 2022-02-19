# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json

import pytest

from pants.backend.codegen.protobuf.lint.buf.rules import BufFieldSet, BufRequest
from pants.backend.codegen.protobuf.lint.buf.rules import rules as buf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files, external_tool, source_files
from pants.engine.addresses import Address
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
            QueryRule(LintResults, [BufRequest]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


GOOD_FILE = 'syntax = "proto3";\npackage foo.v1;\nmessage Foo {\nstring snake_case = 1;\n}\n'
BAD_FILE = 'syntax = "proto3";\npackage foo.v1;\nmessage Bar {\nstring camelCase = 1;\n}\n'


def run_buf(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.codegen.protobuf.lint.buf", *(extra_args or ())],
        env_inherit={"PATH"},
    )
    results = rule_runner.request(
        LintResults,
        [BufRequest(BufFieldSet.create(tgt) for tgt in targets)],
    )
    return results.results


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_buf(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert not result[0].stdout
    assert not result[0].stderr


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo/v1/f.proto": GOOD_FILE, "foo/v1/BUILD": "protobuf_sources(name='t')"}
    )
    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))
    assert_success(rule_runner, tgt)


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo/v1/f.proto": BAD_FILE, "foo/v1/BUILD": "protobuf_sources(name='t')"}
    )
    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))
    result = run_buf(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 100
    assert "foo/v1/f.proto:" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/v1/good.proto": GOOD_FILE,
            "foo/v1/bad.proto": BAD_FILE,
            "foo/v1/BUILD": "protobuf_sources(name='t')",
        }
    )
    tgts = [
        rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="good.proto")),
        rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="bad.proto")),
    ]
    result = run_buf(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 100
    assert "good.proto" not in result[0].stdout
    assert "foo/v1/bad.proto:" in result[0].stdout


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo/v1/f.proto": BAD_FILE, "foo/v1/BUILD": "protobuf_sources(name='t')"}
    )
    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))
    config = json.dumps(
        {
            "version": "v1",
            "lint": {
                "ignore_only": {
                    "FIELD_LOWER_SNAKE_CASE": [
                        "foo/v1/f.proto",
                    ],
                },
            },
        }
    )

    assert_success(
        rule_runner,
        tgt,
        extra_args=[f"--buf-args='--config={config}'"],
    )


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo/v1/f.proto": BAD_FILE, "foo/v1/BUILD": "protobuf_sources(name='t')"}
    )
    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))
    result = run_buf(rule_runner, [tgt], extra_args=["--buf-skip"])
    assert not result


def test_dependencies(rule_runner: RuleRunner) -> None:
    file = 'syntax = "proto3";\npackage bar.v1;\nimport "foo/v1/f.proto";message Baz {\nfoo.v1.Foo foo = 1;\n}\n'
    rule_runner.write_files(
        {
            "foo/v1/f.proto": GOOD_FILE,
            "bar/v1/f.proto": file,
            "foo/v1/BUILD": "protobuf_sources(name='t')",
            "bar/v1/BUILD": "protobuf_sources(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("bar/v1", target_name="t", relative_file_path="f.proto"))
    assert_success(rule_runner, tgt)
