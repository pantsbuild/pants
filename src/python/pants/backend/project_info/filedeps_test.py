# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.codegen.protobuf.target_types import ProtobufSourceTarget
from pants.backend.project_info import filedeps
from pants.engine.target import Dependencies, MultipleSourcesField, SingleSourceField, Target
from pants.testutil.rule_runner import RuleRunner


class MockSources(MultipleSourcesField):
    default = ("*.ext",)


class MockDepsField(Dependencies):
    pass


class MockTarget(Target):
    alias = "tgt"
    core_fields = (MockSources, MockDepsField)


class MockSingleSourceField(SingleSourceField):
    pass


class MockSingleSourceTarget(Target):
    alias = "single_source"
    core_fields = (MockSingleSourceField, MockDepsField)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=filedeps.rules(),
        target_types=[MockTarget, MockSingleSourceTarget, ProtobufSourceTarget],
    )


def assert_filedeps(
    rule_runner: RuleRunner,
    *,
    targets: list[str],
    expected: set[str],
    transitive: bool = False,
    globs: bool = False,
) -> None:
    args = []
    if globs:
        args.append("--filedeps-globs")
    if transitive:
        args.append("--filedeps-transitive")
    result = rule_runner.run_goal_rule(filedeps.Filedeps, args=(*args, *targets))
    assert result.stdout.splitlines() == sorted(expected)


def test_no_target(rule_runner: RuleRunner) -> None:
    assert_filedeps(rule_runner, targets=[], expected=set())


def test_one_target_no_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"a/BUILD": "tgt()"})
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD"})


def test_one_target_one_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/f.ext": "",
            "a/BUILD": "tgt()",
            "b/f.ext": "",
            "b/BUILD": "single_source(source='f.ext')",
        }
    )
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD", "a/f.ext"})
    assert_filedeps(rule_runner, targets=["b"], expected={"b/BUILD", "b/f.ext"})


def test_one_target_multiple_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"a/f1.ext": "", "a/f2.ext": "", "a/BUILD": "tgt()"})
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD", "a/f1.ext", "a/f2.ext"})


def test_one_target_no_source_one_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dep/f.ext": "",
            "dep/BUILD": "tgt()",
            "a/BUILD": "tgt(dependencies=['dep'])",
        }
    )
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD"})
    assert_filedeps(
        rule_runner, targets=["a"], transitive=True, expected={"a/BUILD", "dep/BUILD", "dep/f.ext"}
    )


def test_one_target_one_source_with_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dep/f.ext": "",
            "dep/BUILD": "tgt()",
            "a/f.ext": "",
            "a/BUILD": "tgt(dependencies=['dep'])",
        }
    )
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD", "a/f.ext"})
    assert_filedeps(
        rule_runner,
        targets=["a"],
        transitive=True,
        expected={"a/BUILD", "a/f.ext", "dep/BUILD", "dep/f.ext"},
    )


def test_multiple_targets_one_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"a/f.ext": "", "a/BUILD": "tgt()", "b/f.ext": "", "b/BUILD": "tgt()"})
    assert_filedeps(
        rule_runner,
        targets=["a", "b"],
        expected={"a/BUILD", "a/f.ext", "b/BUILD", "b/f.ext"},
    )


def test_multiple_targets_one_source_with_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dep1/f.ext": "",
            "dep1/BUILD": "tgt()",
            "dep2/f.ext": "",
            "dep2/BUILD": "tgt()",
            "a/f.ext": "",
            "a/BUILD": "tgt(dependencies=['dep1'])",
            "b/f.ext": "",
            "b/BUILD": "tgt(dependencies=['dep2'])",
        }
    )
    direct_files = {
        "a/BUILD",
        "a/f.ext",
        "b/BUILD",
        "b/f.ext",
    }
    assert_filedeps(rule_runner, targets=["a", "b"], expected=direct_files)
    assert_filedeps(
        rule_runner,
        targets=["a", "b"],
        transitive=True,
        expected={*direct_files, "dep1/BUILD", "dep1/f.ext", "dep2/BUILD", "dep2/f.ext"},
    )


def test_multiple_targets_one_source_overlapping(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dep/f.ext": "",
            "dep/BUILD": "tgt()",
            "a/f.ext": "",
            "a/BUILD": "tgt(dependencies=['dep'])",
            "b/f.ext": "",
            "b/BUILD": "tgt(dependencies=['dep'])",
        }
    )
    direct_files = {"a/BUILD", "a/f.ext", "b/BUILD", "b/f.ext"}
    assert_filedeps(rule_runner, targets=["a", "b"], expected=direct_files)
    assert_filedeps(
        rule_runner,
        targets=["a", "b"],
        transitive=True,
        expected={*direct_files, "dep/BUILD", "dep/f.ext"},
    )


def test_globs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "a/test1.ext": "",
            "a/test2.ext": "",
            "a/BUILD": "tgt(sources=['test*.ext'])",
        }
    )
    assert_filedeps(
        rule_runner,
        targets=["a"],
        expected={"a/BUILD", "a/test*.ext"},
        globs=True,
    )


def test_build_with_file_ext(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"a/BUILD.ext": "tgt()"})
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD.ext"})


def test_codegen_targets_use_protocol_files(rule_runner: RuleRunner) -> None:
    # That is, don't output generated files.
    rule_runner.write_files({"a/f.proto": "", "a/BUILD": "protobuf_source(source='f.proto')"})
    assert_filedeps(rule_runner, targets=["a"], expected={"a/BUILD", "a/f.proto"})
