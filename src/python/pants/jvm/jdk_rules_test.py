# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.process import rules as process_rules
from pants.jvm.jdk_rules import JdkSetup, parse_jre_major_version
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.user_resolves import rules as coursier_fetch_rules
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *source_files.rules(),
            *coursier_setup_rules(),
            *coursier_fetch_rules(),
            *external_tool_rules(),
            *util_rules(),
            *jdk_rules(),
            *process_rules(),
            QueryRule(BashBinary, ()),
            QueryRule(JdkSetup, ()),
            QueryRule(ProcessResult, (Process,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


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
                append_only_caches=jdk_setup.append_only_caches,
                immutable_input_digests=jdk_setup.immutable_input_digests,
                env=jdk_setup.env,
                description="",
            )
        ],
    )
    return "\n".join(
        [process_result.stderr.decode("utf-8"), process_result.stdout.decode("utf-8")],
    )


@maybe_skip_jdk_test
def test_java_binary_system_version(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--jvm-jdk=system"], env_inherit=PYTHON_BOOTSTRAP_ENV)
    assert "openjdk version" in run_javac_version(rule_runner)


@maybe_skip_jdk_test
def test_java_binary_bogus_version_fails(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--jvm-jdk=bogusjdk:999"], env_inherit=PYTHON_BOOTSTRAP_ENV)
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        run_javac_version(rule_runner)


@maybe_skip_jdk_test
@pytest.mark.skip(reason="#12293 Coursier JDK bootstrapping is currently flaky in CI")
def test_java_binary_versions(rule_runner: RuleRunner) -> None:
    # default version is 1.11
    assert "javac 11.0" in run_javac_version(rule_runner)

    rule_runner.set_options(["--jvm-jdk=adopt:1.8"], env_inherit=PYTHON_BOOTSTRAP_ENV)
    assert "javac 1.8" in run_javac_version(rule_runner)

    rule_runner.set_options(["--jvm-jdk=bogusjdk:999"], env_inherit=PYTHON_BOOTSTRAP_ENV)
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        assert "javac 16.0" in run_javac_version(rule_runner)


@maybe_skip_jdk_test
def test_parse_java_version() -> None:
    version1 = textwrap.dedent(
        """\
    openjdk version "17.0.1" 2021-10-19
    OpenJDK Runtime Environment Homebrew (build 17.0.1+0)
    OpenJDK 64-Bit Server VM Homebrew (build 17.0.1+0, mixed mode, sharing)
    """
    )
    assert parse_jre_major_version(version1) == 17

    version2 = textwrap.dedent(
        """\
    openjdk version "11" 2018-09-25
    OpenJDK Runtime Environment AdoptOpenJDK (build 11+28)
    OpenJDK 64-Bit Server VM AdoptOpenJDK (build 11+28, mixed mode)
    """
    )
    assert parse_jre_major_version(version2) == 11
