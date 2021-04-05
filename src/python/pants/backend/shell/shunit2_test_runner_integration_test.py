# Copyright 2021 Pants project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.shell import shunit2_test_runner
from pants.backend.shell.shunit2_test_runner import (
    Shunit2FieldSet,
    Shunit2Runner,
    Shunit2RunnerRequest,
)
from pants.backend.shell.target_types import (
    ShellLibrary,
    Shunit2Shell,
    Shunit2ShellField,
    Shunit2Tests,
)
from pants.core.goals.test import TestDebugRequest, TestResult, get_filtered_environment
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import InteractiveRunner
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, mock_console


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *shunit2_test_runner.rules(),
            *source_files.rules(),
            get_filtered_environment,
            QueryRule(TestResult, [Shunit2FieldSet]),
            QueryRule(TestDebugRequest, [Shunit2FieldSet]),
            QueryRule(Shunit2Runner, [Shunit2RunnerRequest]),
        ],
        target_types=[ShellLibrary, Shunit2Tests],
    )


GOOD_TEST = dedent(
    """\
    #!/usr/bin/bash

    testEquality() {
        assertEquals 1 1
    }
    """
)


def run_shunit2(
    rule_runner: RuleRunner,
    test_target: Target,
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> TestResult:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.shell",
            *(extra_args or ()),
        ],
        env=env,
        env_inherit={"PATH"},
    )
    inputs = [Shunit2FieldSet.create(test_target)]
    test_result = rule_runner.request(TestResult, inputs)
    debug_request = rule_runner.request(TestDebugRequest, inputs)
    if debug_request.process is not None:
        with mock_console(rule_runner.options_bootstrapper):
            debug_result = InteractiveRunner(rule_runner.scheduler).run(debug_request.process)
            assert test_result.exit_code == debug_result.exit_code
    return test_result


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"tests.sh": GOOD_TEST, "BUILD": "shunit2_tests(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="tests.sh"))
    result = run_shunit2(rule_runner, tgt)
    assert result.exit_code == 0
    assert "Ran 1 test.\n\nOK" in result.stdout


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "tests.sh": dedent(
                """\
                #!/usr/bin/bash

                testEquality() {
                    assertEquals 1 5
                }
                """
            ),
            "BUILD": "shunit2_tests(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="tests.sh"))
    result = run_shunit2(rule_runner, tgt)
    assert result.exit_code == 1
    assert "Ran 1 test.\n\nFAILED" in result.stdout


def test_dependencies(rule_runner: RuleRunner) -> None:
    """Ensure direct and transitive dependencies work."""
    rule_runner.write_files(
        {
            "transitive.sh": dedent(
                """\
                add_one() {
                    echo $(($1 + 1))
                }
                """
            ),
            "direct.sh": dedent(
                """\
                source transitive.sh

                add_two() {
                    echo $(($(add_one $1) + 1))
                }
                """
            ),
            "tests.sh": dedent(
                """\
                #!/usr/bin/bash

                source direct.sh

                testAdd() {
                    assertEquals $(add_two 2) 4
                }
                """
            ),
            "BUILD": dedent(
                """\
                shunit2_tests(name="t", dependencies=[':direct'])
                shell_library(name="direct", sources=['direct.sh'], dependencies=[':transitive'])
                shell_library(name="transitive", sources=['transitive.sh'])
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="tests.sh"))
    result = run_shunit2(rule_runner, tgt)
    assert result.exit_code == 0
    assert "Ran 1 test.\n\nOK" in result.stdout


def test_subdirectories(rule_runner: RuleRunner) -> None:
    # We always download the shunit2 script to the build root - this test is a smoke screen that
    # we properly source the file.
    rule_runner.write_files({"a/b/c/tests.sh": GOOD_TEST, "a/b/c/BUILD": "shunit2_tests()"})
    tgt = rule_runner.get_target(Address("a/b/c", relative_file_path="tests.sh"))
    result = run_shunit2(rule_runner, tgt)
    assert result.exit_code == 0
    assert "Ran 1 test.\n\nOK" in result.stdout


@pytest.mark.skip(
    "TODO: figure out why the rule is getting memoized but that doesn't happen with Pytest."
    "The Process is not being cached, but the rule invocation is being memoized so the "
    "`--force` does not work properly."
)
def test_force(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"tests.sh": GOOD_TEST, "BUILD": "shunit2_tests(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="tests.sh"))

    # Should not receive a memoized result if force=True.
    result_one = run_shunit2(rule_runner, tgt, extra_args=["--test-force"])
    result_two = run_shunit2(rule_runner, tgt, extra_args=["--test-force"])
    assert result_one.exit_code == 0
    assert result_two.exit_code == 0
    assert result_one is not result_two

    # But should if force=False.
    result_one = run_shunit2(rule_runner, tgt)
    result_two = run_shunit2(rule_runner, tgt)
    assert result_one.exit_code == 0
    assert result_one is result_two


def test_extra_env_vars(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "tests.sh": dedent(
                """\
                #!/usr/bin/bash

                testEnv() {
                    assertEquals "${SOME_VAR}" some_value
                    assertEquals "${OTHER_VAR}" other_value
                }
                """
            ),
            "BUILD": "shunit2_tests(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="tests.sh"))
    result = run_shunit2(
        rule_runner,
        tgt,
        extra_args=['--test-extra-env-vars=["SOME_VAR=some_value", "OTHER_VAR"]'],
        env={"OTHER_VAR": "other_value"},
    )
    assert result.exit_code == 0
    assert "Ran 1 test.\n\nOK" in result.stdout


def test_determine_shell_runner(rule_runner: RuleRunner) -> None:
    addr = Address("", target_name="t")
    fc = FileContent("tests.sh", b"#!/usr/bin/env sh")
    rule_runner.set_options([], env_inherit={"PATH"})

    # If `shell` field is not set, read the shebang.
    result = rule_runner.request(
        Shunit2Runner, [Shunit2RunnerRequest(addr, fc, Shunit2ShellField(None, address=addr))]
    )
    assert result.shell == Shunit2Shell.sh

    # The `shell` field overrides the shebang.
    result = rule_runner.request(
        Shunit2Runner, [Shunit2RunnerRequest(addr, fc, Shunit2ShellField("bash", address=addr))]
    )
    assert result.shell == Shunit2Shell.bash

    # Error if not set.
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(
            Shunit2Runner,
            [
                Shunit2RunnerRequest(
                    addr, FileContent("tests.sh", b""), Shunit2ShellField(None, address=addr)
                )
            ],
        )
    assert f"Could not determine which shell to use to run shunit2 on {addr}" in str(exc.value)
