# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.adhoc import run_system_binary
from pants.backend.adhoc.target_types import SystemBinaryTarget
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
from pants.core.util_rules import archive, source_files, system_binaries
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents, FileContent
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
            *system_binaries.rules(),
            *run_system_binary.rules(),
            get_filtered_environment,
            QueryRule(TestResult, (ShellTestRequest.Batch,)),
            QueryRule(TestDebugRequest, [ShellTestRequest.Batch]),
        ],
        target_types=[
            ShellSourcesGeneratorTarget,
            ShellCommandTarget,
            ShellCommandTestTarget,
            SystemBinaryTarget,
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

                test_shell_command(
                  name="pass",
                  execution_dependencies=[":msg-gen", ":src"],
                  tools=["echo"],
                  command="./test.sh msg.txt message",
                )

                test_shell_command(
                  name="fail",
                  execution_dependencies=[":msg-gen", ":src"],
                  tools=["echo"],
                  command="./test.sh msg.txt xyzzy",
                )

                # Check whether `runnable_dependencies` works.
                system_binary(
                    name="cat",
                    binary_name="cat",
                )
                system_binary(
                    name="test",
                    binary_name="test",
                    fingerprint_args=["1", "=", "1"]
                )
                test_shell_command(
                  name="pass_with_runnable_dependency",
                  execution_dependencies=[":msg-gen", ":src"],
                  tools=["echo"],
                  runnable_dependencies=[":cat", ":test"],
                  command="value=$(cat msg.txt) && test $value = message",
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

    pass_for_runnable_dependency_target = rule_runner.get_target(
        Address("", target_name="pass_with_runnable_dependency")
    )
    pass_for_runnable_dependency_result = run_test(pass_for_runnable_dependency_target)
    assert pass_for_runnable_dependency_result.exit_code == 0


@pytest.mark.platform_specific_behavior
def test_extra_outputs_support(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                shell_sources(name="src")

                test_shell_command(
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
            test_shell_command(
                name="allow_empty",
                command="true",
                output_files=["non-existent-file"],
                output_directories=["non-existent-dir"],
                outputs_match_mode="allow_empty",
            )
            test_shell_command(
                name="all_with_present_file",
                command="touch some-file",
                tools=["touch"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="all",
            )
            test_shell_command(
                name="all_with_present_directory",
                command="mkdir some-directory",
                tools=["mkdir"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="all",
            )
            test_shell_command(
                name="at_least_one_with_present_file",
                command="touch some-file",
                tools=["touch"],
                output_files=["some-file"],
                output_directories=["some-directory"],
                outputs_match_mode="at_least_one",
            )
            test_shell_command(
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


def test_cache_scope_support(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
            test_shell_command(
              name="cmd_session_scope",
              # Use a random value so we can detect when re-execution occurs.
              command="echo $RANDOM > out.log",
              output_files=["out.log"],
              cache_scope="session",
            )
            test_shell_command(
              name="cmd_success_scope",
              # Use a random value so we can detect when re-execution occurs.
              command="echo $RANDOM > out.log",
              output_files=["out.log"],
              cache_scope="success",
            )
            """
            ),
            "src/a-file": "",
        }
    )

    def test_batch_for_target(test_target: Target) -> ShellTestRequest.Batch:
        return ShellTestRequest.Batch("", (TestShellCommandFieldSet.create(test_target),), None)

    def run_test(address: Address) -> TestResult:
        test_target = rule_runner.get_target(address)
        return rule_runner.request(TestResult, [test_batch_for_target(test_target)])

    def test_output_equal(result1: TestResult, result2: TestResult) -> bool:
        digest1: Digest = EMPTY_DIGEST
        if result1.extra_output:
            digest1 = result1.extra_output.digest

        digest2: Digest = EMPTY_DIGEST
        if result2.extra_output:
            digest2 = result2.extra_output.digest

        return digest1 == digest2

    # Re-executing the initial execution of a session-scoped test should be cached if in the same session.
    address_session = Address("src", target_name="cmd_session_scope")
    session_result_1 = run_test(address_session)
    session_result_2 = run_test(address_session)
    assert test_output_equal(session_result_1, session_result_2)

    # Execute the success-scoped test to ensure it is cached (for testing in the new session).
    address_success = Address("src", target_name="cmd_success_scope")
    success_result_1 = run_test(address_success)

    # Create a new session.
    rule_runner.new_session("second-session")
    rule_runner.set_options([])

    # In a new session, the session-scoped test should be re-executed.
    session_result_3 = run_test(address_session)
    assert not test_output_equal(session_result_2, session_result_3)

    # In a new session, the success-scoped test should NOT be re-executed.
    success_result_2 = run_test(address_success)
    assert test_output_equal(success_result_1, success_result_2)
