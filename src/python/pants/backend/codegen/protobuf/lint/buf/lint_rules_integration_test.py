# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any

import pytest

from pants.backend.codegen.protobuf.lint.buf.lint_rules import BufFieldSet, BufLintRequest
from pants.backend.codegen.protobuf.lint.buf.lint_rules import rules as buf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files, external_tool, stripped_source_files
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
            *stripped_source_files.rules(),
            *target_types_rules(),
            QueryRule(Partitions, [BufLintRequest.PartitionRequest]),
            QueryRule(LintResult, [BufLintRequest.Batch]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


GOOD_FILE = 'syntax = "proto3";\npackage foo.v1;\nmessage Foo {\nstring snake_case = 1;\n}\n'
BAD_FILE = 'syntax = "proto3";\npackage foo.v1;\nmessage Bar {\nstring camelCase = 1;\n}\n'


def run_buf(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    source_roots: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_roots)}",
            "--backend-packages=pants.backend.codegen.protobuf.lint.buf",
            *(extra_args or ()),
        ],
        env_inherit={"PATH"},
    )
    partitions = rule_runner.request(
        Partitions[BufFieldSet, Any],
        [BufLintRequest.PartitionRequest(tuple(BufFieldSet.create(tgt) for tgt in targets))],
    )
    results = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [BufLintRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(
    rule_runner: RuleRunner,
    target: Target,
    *,
    source_roots: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> None:
    result = run_buf(rule_runner, [target], source_roots=source_roots, extra_args=extra_args)
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
        extra_args=[f"--buf-lint-args='--config={config}'"],
    )


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo/v1/f.proto": BAD_FILE, "foo/v1/BUILD": "protobuf_sources(name='t')"}
    )
    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))
    result = run_buf(rule_runner, [tgt], extra_args=["--buf-lint-skip"])
    assert not result


def test_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/protobuf/dir1/v1/f.proto": dedent(
                """\
                syntax = "proto3";
                package dir1.v1;
                message Person {
                  string name = 1;
                  int32 id = 2;
                  string email = 3;
                }
                """
            ),
            "src/protobuf/dir1/v1/BUILD": "protobuf_sources()",
            "src/protobuf/dir2/v1/f.proto": dedent(
                """\
                syntax = "proto3";
                package dir2.v1;
                import "dir1/v1/f.proto";

                message Person {
                  dir1.v1.Person person = 1;
                }
                """
            ),
            "src/protobuf/dir2/v1/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir1/v1'])"
            ),
            "tests/protobuf/test_protos/v1/f.proto": dedent(
                """\
                syntax = "proto3";
                package test_protos.v1;
                import "dir2/v1/f.proto";

                message Person {
                  dir2.v1.Person person = 1;
                }
                """
            ),
            "tests/protobuf/test_protos/v1/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir2/v1'])"
            ),
        }
    )

    tgt = rule_runner.get_target(
        Address("tests/protobuf/test_protos/v1", relative_file_path="f.proto")
    )
    assert_success(
        rule_runner, tgt, source_roots=["src/python", "/src/protobuf", "/tests/protobuf"]
    )


def test_config_discovery(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/v1/f.proto": BAD_FILE,
            "foo/v1/BUILD": "protobuf_sources(name='t')",
            "buf.yaml": dedent(
                """\
             version: v1
             lint:
               ignore_only:
                 FIELD_LOWER_SNAKE_CASE:
                   - foo/v1/f.proto
             """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))

    assert_success(
        rule_runner,
        tgt,
    )


def test_config_file_submitted(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/v1/f.proto": BAD_FILE,
            "foo/v1/BUILD": "protobuf_sources(name='t')",
            # Intentionally placed somewhere config_discovery can't see.
            "foo/buf.yaml": dedent(
                """\
             version: v1
             lint:
               ignore_only:
                 FIELD_LOWER_SNAKE_CASE:
                   - foo/v1/f.proto
             """,
            ),
        }
    )

    tgt = rule_runner.get_target(Address("foo/v1", target_name="t", relative_file_path="f.proto"))

    assert_success(
        rule_runner,
        tgt,
        extra_args=["--buf-config=foo/buf.yaml"],
    )
