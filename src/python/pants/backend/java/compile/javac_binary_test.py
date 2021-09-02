# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.compile.javac_binary import JavacBinary
from pants.backend.java.compile.javac_binary import rules as javac_binary_rules
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.process import rules as process_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner

# TODO(#12293): Stabilize flakiness.
pytestmark = pytest.mark.skip


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *coursier_setup_rules(),
            *external_tool_rules(),
            *javac_binary_rules(),
            *process_rules(),
            QueryRule(BashBinary, ()),
            QueryRule(JavacBinary, ()),
            QueryRule(ProcessResult, (Process,)),
        ],
    )


def run_javac_version(rule_runner: RuleRunner) -> str:
    javac_binary = rule_runner.request(JavacBinary, [])
    bash = rule_runner.request(BashBinary, [])
    process_result = rule_runner.request(
        ProcessResult,
        [
            Process(
                argv=[
                    bash.path,
                    javac_binary.javac_wrapper_script,
                    "-version",
                ],
                input_digest=javac_binary.digest,
                description="",
            )
        ],
    )
    return "\n".join(
        [process_result.stderr.decode("utf-8"), process_result.stdout.decode("utf-8")],
    )


def test_java_binary_system_version(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--javac-jdk=system"])
    assert "javac" in run_javac_version(rule_runner)


def test_java_binary_bogus_version_fails(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--javac-jdk=bogusjdk:999"])
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        run_javac_version(rule_runner)


@pytest.mark.skip(reason="#12293 Coursier JDK bootstrapping is currently flaky in CI")
def test_java_binary_versions(rule_runner: RuleRunner) -> None:
    # default version is 1.11
    assert "javac 11.0" in run_javac_version(rule_runner)

    rule_runner.set_options(["--javac-jdk=adopt:1.8"])
    assert "javac 1.8" in run_javac_version(rule_runner)

    rule_runner.set_options(["--javac-jdk=bogusjdk:999"])
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        assert "javac 16.0" in run_javac_version(rule_runner)
