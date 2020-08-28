# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Set

import pytest

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.project_info import filedeps
from pants.engine.target import Dependencies, Sources, Target
from pants.testutil.rule_runner import RuleRunner


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Sources, Dependencies)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=filedeps.rules(), target_types=[MockTarget, ProtobufLibrary])


def setup_target(
    rule_runner: RuleRunner,
    path: str,
    *,
    sources: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None,
) -> None:
    if sources:
        rule_runner.create_files(path, sources)
    rule_runner.add_to_build_file(
        path,
        f"tgt(sources={sources or []}, dependencies={dependencies or []})",
    )


def assert_filedeps(
    rule_runner: RuleRunner,
    *,
    targets: List[str],
    expected: Set[str],
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
    setup_target(rule_runner, "some/target")
    assert_filedeps(rule_runner, targets=["some/target"], expected={"some/target/BUILD"})


def test_one_target_one_source(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "some/target", sources=["file.py"])
    assert_filedeps(
        rule_runner, targets=["some/target"], expected={"some/target/BUILD", "some/target/file.py"}
    )


def test_one_target_multiple_source(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "some/target", sources=["file1.py", "file2.py"])
    assert_filedeps(
        rule_runner,
        targets=["some/target"],
        expected={"some/target/BUILD", "some/target/file1.py", "some/target/file2.py"},
    )


def test_one_target_no_source_one_dep(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "dep/target", sources=["file.py"])
    setup_target(rule_runner, "some/target", dependencies=["dep/target"])
    assert_filedeps(rule_runner, targets=["some/target"], expected={"some/target/BUILD"})
    assert_filedeps(
        rule_runner,
        targets=["some/target"],
        transitive=True,
        expected={"some/target/BUILD", "dep/target/BUILD", "dep/target/file.py"},
    )


def test_one_target_one_source_with_dep(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "dep/target", sources=["file.py"])
    setup_target(rule_runner, "some/target", sources=["file.py"], dependencies=["dep/target"])
    direct_files = {"some/target/BUILD", "some/target/file.py"}
    assert_filedeps(rule_runner, targets=["some/target"], expected=direct_files)
    assert_filedeps(
        rule_runner,
        targets=["some/target"],
        transitive=True,
        expected={
            *direct_files,
            "dep/target/BUILD",
            "dep/target/file.py",
        },
    )


def test_multiple_targets_one_source(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "some/target", sources=["file.py"])
    setup_target(rule_runner, "other/target", sources=["file.py"])
    assert_filedeps(
        rule_runner,
        targets=["some/target", "other/target"],
        expected={
            "some/target/BUILD",
            "some/target/file.py",
            "other/target/BUILD",
            "other/target/file.py",
        },
    )


def test_multiple_targets_one_source_with_dep(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "dep1/target", sources=["file.py"])
    setup_target(rule_runner, "dep2/target", sources=["file.py"])
    setup_target(rule_runner, "some/target", sources=["file.py"], dependencies=["dep1/target"])
    setup_target(rule_runner, "other/target", sources=["file.py"], dependencies=["dep2/target"])
    direct_files = {
        "some/target/BUILD",
        "some/target/file.py",
        "other/target/BUILD",
        "other/target/file.py",
    }
    assert_filedeps(
        rule_runner,
        targets=["some/target", "other/target"],
        expected=direct_files,
    )
    assert_filedeps(
        rule_runner,
        targets=["some/target", "other/target"],
        transitive=True,
        expected={
            *direct_files,
            "dep1/target/BUILD",
            "dep1/target/file.py",
            "dep2/target/BUILD",
            "dep2/target/file.py",
        },
    )


def test_multiple_targets_one_source_overlapping(rule_runner: RuleRunner) -> None:
    setup_target(rule_runner, "dep/target", sources=["file.py"])
    setup_target(rule_runner, "some/target", sources=["file.py"], dependencies=["dep/target"])
    setup_target(rule_runner, "other/target", sources=["file.py"], dependencies=["dep/target"])
    direct_files = {
        "some/target/BUILD",
        "some/target/file.py",
        "other/target/BUILD",
        "other/target/file.py",
    }
    assert_filedeps(rule_runner, targets=["some/target", "other/target"], expected=direct_files)
    assert_filedeps(
        rule_runner,
        targets=["some/target", "other/target"],
        transitive=True,
        expected={*direct_files, "dep/target/BUILD", "dep/target/file.py"},
    )


def test_globs(rule_runner: RuleRunner) -> None:
    rule_runner.create_files("some/target", ["test1.py", "test2.py"])
    rule_runner.add_to_build_file("some/target", target="tgt(sources=['test*.py'])")
    assert_filedeps(
        rule_runner,
        targets=["some/target"],
        expected={"some/target/BUILD", "some/target/test*.py"},
        globs=True,
    )


def test_build_with_file_ext(rule_runner: RuleRunner) -> None:
    rule_runner.create_file("some/target/BUILD.ext", contents="tgt()")
    assert_filedeps(rule_runner, targets=["some/target"], expected={"some/target/BUILD.ext"})


def test_codegen_targets_use_protocol_files(rule_runner: RuleRunner) -> None:
    # That is, don't output generated files.
    rule_runner.create_file("some/target/f.proto")
    rule_runner.add_to_build_file("some/target", "protobuf_library()")
    assert_filedeps(
        rule_runner, targets=["some/target"], expected={"some/target/BUILD", "some/target/f.proto"}
    )
