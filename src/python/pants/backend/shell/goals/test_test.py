# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.shell.goals import test
from pants.backend.shell.goals.test import ShellTestRequest, TestShellCommandFieldSet
from pants.backend.shell.target_types import (
    ShellCommandTarget,
    ShellCommandTestTarget,
    ShellSourcesGeneratorTarget,
)
from pants.build_graph.address import Address
from pants.core.goals import package
from pants.core.goals.test import TestDebugRequest, TestResult, get_filtered_environment
from pants.core.util_rules import archive, source_files
from pants.engine.fs import DigestContents, FileContent
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner, mock_console

ATTEMPTS_DEFAULT_OPTION = 2


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test.rules(),
            *source_files.rules(),
            *archive.rules(),
            *package.rules(),
            get_filtered_environment,
            QueryRule(TestResult, (ShellTestRequest.Batch,)),
            QueryRule(TestDebugRequest, [ShellTestRequest.Batch]),
        ],
        target_types=[
            ShellSourcesGeneratorTarget,
            ShellCommandTarget,
            ShellCommandTestTarget,
        ],
    )
    rule_runner.set_options(
        [f"--test-attempts-default={ATTEMPTS_DEFAULT_OPTION}"], env_inherit={"PATH"}
    )
    return rule_runner


@pytest.mark.platform_specific_behavior
def test_basic_usage_of_test_shell_command(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                shell_sources(name="src")

                shell_command(
                  name="msg-gen",
                  command="echo message > msg.txt",
                  tools=["echo"],
                  output_files=["msg.txt"],
                )

                experimental_test_shell_command(
                  name="pass",
                  execution_dependencies=[":msg-gen", ":src"],
                  tools=["echo"],
                  command="./test.sh msg.txt message",
                )

                experimental_test_shell_command(
                  name="fail",
                  execution_dependencies=[":msg-gen", ":src"],
                  tools=["echo"],
                  command="./test.sh msg.txt xyzzy",
                )
                """
            ),
            "test.sh": dedent(
                """\
                contents="$(<$1)"
                if [ "$contents" = "$2" ]; then
                  echo "contains '$2'"
                  exit 0
                else
                  echo "does not contain '$2'"
                  exit 1
                fi
                """
            ),
        }
    )
    (Path(rule_runner.build_root) / "test.sh").chmod(0o555)

    def test_batch_for_target(test_target: Target) -> ShellTestRequest.Batch:
        return ShellTestRequest.Batch("", (TestShellCommandFieldSet.create(test_target),), None)

    def run_test(test_target: Target) -> TestResult:
        return rule_runner.request(TestResult, [test_batch_for_target(test_target)])

    pass_target = rule_runner.get_target(Address("", target_name="pass"))
    pass_result = run_test(pass_target)
    assert pass_result.exit_code == 0
    assert pass_result.stdout_bytes == b"contains 'message'\n"

    fail_target = rule_runner.get_target(Address("", target_name="fail"))
    fail_result = run_test(fail_target)
    assert fail_result.exit_code == 1
    assert fail_result.stdout_bytes == b"does not contain 'xyzzy'\n"
    assert len(fail_result.process_results) == ATTEMPTS_DEFAULT_OPTION

    # Check whether interactive execution via the `test` goal's `--debug` flags succeeds.
    pass_debug_request = rule_runner.request(TestDebugRequest, [test_batch_for_target(pass_target)])
    with mock_console(rule_runner.options_bootstrapper):
        pass_debug_result = rule_runner.run_interactive_process(pass_debug_request.process)
        assert pass_debug_result.exit_code == 0

    fail_debug_request = rule_runner.request(TestDebugRequest, [test_batch_for_target(fail_target)])
    with mock_console(rule_runner.options_bootstrapper):
        fail_debug_result = rule_runner.run_interactive_process(fail_debug_request.process)
        assert fail_debug_result.exit_code == 1


@pytest.mark.platform_specific_behavior
def test_extra_outputs_support(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                shell_sources(name="src")

                experimental_test_shell_command(
                  name="test",
                  execution_dependencies=[":src"],
                  tools=["echo", "mkdir"],
                  command="./test.sh msg.txt message",
                  output_files=["world.txt"],
                  output_directories=["some-dir"],
                )
                """
            ),
            "test.sh": dedent(
                """\
                mkdir -p some-dir
                echo "xyzzy" > some-dir/foo.txt
                echo "hello" > world.txt
                """
            ),
        }
    )
    (Path(rule_runner.build_root) / "test.sh").chmod(0o555)

    def test_batch_for_target(test_target: Target) -> ShellTestRequest.Batch:
        return ShellTestRequest.Batch("", (TestShellCommandFieldSet.create(test_target),), None)

    def run_test(test_target: Target) -> TestResult:
        return rule_runner.request(TestResult, [test_batch_for_target(test_target)])

    result = run_test(rule_runner.get_target(Address("", target_name="test")))
    assert result.extra_output is not None
    digest_contents = rule_runner.request(DigestContents, [result.extra_output.digest])
    digest_contents_sorted = sorted(digest_contents, key=lambda x: x.path)
    assert len(digest_contents_sorted) == 2
    assert digest_contents_sorted[0] == FileContent("some-dir/foo.txt", b"xyzzy\n")
    assert digest_contents_sorted[1] == FileContent("world.txt", b"hello\n")


def test_outputs_match_mode_support(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            experimental_test_shell_command(
                name="allow_empty",
                command="true",
                output_files=["non-existent-file"],
                output_directories=["non-existent-dir"],
                outputs_match_mode="allow_empty",
            )
            experimental_test_shell_command(
                name="all_with_present_file",
                command="touch some-file",
                tools=["touch"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="all",
            )
            experimental_test_shell_command(
                name="all_with_present_directory",
                command="mkdir some-directory",
                tools=["mkdir"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="all",
            )
            experimental_test_shell_command(
                name="at_least_one_with_present_file",
                command="touch some-file",
                tools=["touch"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="at_least_one",
            )
            experimental_test_shell_command(
                name="at_least_one_with_present_directory",
                command="mkdir some-directory && touch some-directory/foo.txt",
                tools=["mkdir", "touch"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="at_least_one",
            )
            """
            )
        }
    )

    def test_batch_for_target(test_target: Target) -> ShellTestRequest.Batch:
        return ShellTestRequest.Batch("", (TestShellCommandFieldSet.create(test_target),), None)

    def run_test(address: Address) -> TestResult:
        test_target = rule_runner.get_target(address)
        return rule_runner.request(TestResult, [test_batch_for_target(test_target)])

    def assert_result(
        address: Address,
        expected_contents: dict[str, str],
    ) -> None:
        result = run_test(address)
        if expected_contents:
            assert result.extra_output
            assert result.extra_output.files == tuple(expected_contents)

            contents = rule_runner.request(DigestContents, [result.extra_output.digest])
            for fc in contents:
                assert fc.content == expected_contents[fc.path].encode()

    assert_result(Address("", target_name="allow_empty"), {})

    with pytest.raises(ExecutionError) as exc_info:
        run_test(Address("", target_name="all_with_present_file"))
    assert "some-directory" in str(exc_info)

    with pytest.raises(ExecutionError) as exc_info:
        run_test(Address("", target_name="all_with_present_directory"))
    assert "some-file" in str(exc_info)

    assert_result(Address("", target_name="at_least_one_with_present_file"), {"some-file": ""})
    assert_result(
        Address("", target_name="at_least_one_with_present_directory"),
        {"some-directory/foo.txt": ""},
    )
