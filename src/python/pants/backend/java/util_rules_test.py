# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.util_rules import JdkSetup
from pants.backend.java.util_rules import rules as java_util_rules
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.process import rules as process_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *source_files.rules(),
            *coursier_setup_rules(),
            *coursier_fetch_rules(),
            *external_tool_rules(),
            *util_rules(),
            *java_util_rules(),
            *process_rules(),
            QueryRule(BashBinary, ()),
            QueryRule(JdkSetup, ()),
            QueryRule(ProcessResult, (Process,)),
        ],
    )


def run_javac_version(rule_runner: RuleRunner) -> str:
    jdk_setup = rule_runner.request(JdkSetup, [])
    bash = rule_runner.request(BashBinary, [])
    process_result = rule_runner.request(
        ProcessResult,
        [
            Process(
                argv=[
                    *jdk_setup.args(bash, []),
                    "-version",
                ],
                input_digest=jdk_setup.digest,
                description="",
            )
        ],
    )
    return "\n".join(
        [process_result.stderr.decode("utf-8"), process_result.stdout.decode("utf-8")],
    )


@maybe_skip_jdk_test
def test_java_binary_system_version(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--javac-jdk=system"])
    assert "openjdk version" in run_javac_version(rule_runner)


@maybe_skip_jdk_test
def test_java_binary_bogus_version_fails(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--javac-jdk=bogusjdk:999"])
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        run_javac_version(rule_runner)


@maybe_skip_jdk_test
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
