# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, DigestContents, FileContent
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import (
    BinaryPathRequest,
    BinaryPaths,
    FallibleProcessResult,
    InteractiveProcess,
    Process,
    ProcessCacheScope,
    ProcessResult,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir, touch


def new_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(BinaryPaths, [BinaryPathRequest]),
            QueryRule(ProcessResult, [Process]),
            QueryRule(FallibleProcessResult, [Process]),
        ],
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return new_rule_runner()


def test_argv_executable(rule_runner: RuleRunner) -> None:
    def run_process(*, is_executable: bool) -> ProcessResult:
        digest = rule_runner.request(
            Digest,
            [
                CreateDigest(
                    [
                        FileContent(
                            "echo.sh",
                            b'#!/bin/bash -eu\necho "Hello"\n',
                            is_executable=is_executable,
                        )
                    ]
                )
            ],
        )
        process = Process(
            argv=("./echo.sh",),
            input_digest=digest,
            description="cat the contents of this file",
        )
        return rule_runner.request(ProcessResult, [process])

    assert run_process(is_executable=True).stdout == b"Hello\n"

    with pytest.raises(ExecutionError) as exc:
        run_process(is_executable=False)
    assert "Permission" in str(exc.value)


def test_env(rule_runner: RuleRunner) -> None:
    with environment_as(VAR1="VAL"):
        process = Process(argv=("/usr/bin/env",), description="", env={"VAR2": "VAL"})
        result = rule_runner.request(ProcessResult, [process])
    assert b"VAR1=VAL" not in result.stdout
    assert b"VAR2=VAL" in result.stdout


def test_output_digest(rule_runner: RuleRunner) -> None:
    process = Process(
        argv=("/bin/bash", "-c", "echo -n 'European Burmese' > roland"),
        description="echo roland",
        output_files=("roland",),
    )
    result = rule_runner.request(ProcessResult, [process])
    assert result.output_digest == Digest(
        fingerprint="63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
        serialized_bytes_length=80,
    )

    digest_contents = rule_runner.request(DigestContents, [result.output_digest])
    assert digest_contents == DigestContents([FileContent("roland", b"European Burmese", False)])


def test_timeout(rule_runner: RuleRunner) -> None:
    process = Process(
        argv=("/bin/bash", "-c", "/bin/sleep 0.2; /bin/echo -n 'European Burmese'"),
        timeout_seconds=0.1,
        description="sleepy-cat",
    )
    result = rule_runner.request(FallibleProcessResult, [process])
    assert result.exit_code != 0
    assert b"Exceeded timeout" in result.stdout
    assert b"sleepy-cat" in result.stdout


def test_failing_process(rule_runner: RuleRunner) -> None:
    process = Process(argv=("/bin/bash", "-c", "exit 1"), description="failure")
    result = rule_runner.request(FallibleProcessResult, [process])
    assert result.exit_code == 1

    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(ProcessResult, [process])
    assert "Process 'failure' failed with exit code 1." in str(exc.value)


def test_cache_scope_always(rule_runner: RuleRunner) -> None:
    # Should not re-run on failure, even in a new Session.
    process = Process(
        argv=("/bin/bash", "-c", "echo $RANDOM && exit 1"),
        cache_scope=ProcessCacheScope.ALWAYS,
        description="failure",
    )
    result_one = rule_runner.request(FallibleProcessResult, [process])
    rule_runner.new_session("session two")
    result_two = rule_runner.request(FallibleProcessResult, [process])
    assert result_one is result_two


def test_cache_scope_successful(rule_runner: RuleRunner) -> None:
    # Should not re-run on success, even in a new Session.
    process = Process(
        argv=("/bin/bash", "-c", "echo $RANDOM"),
        cache_scope=ProcessCacheScope.SUCCESSFUL,
        description="success",
    )
    result_one = rule_runner.request(FallibleProcessResult, [process])
    rule_runner.new_session("session one")
    result_two = rule_runner.request(FallibleProcessResult, [process])
    assert result_one is result_two

    # Should re-run on failure, but only in a new Session.
    process = Process(
        argv=("/bin/bash", "-c", "echo $RANDOM && exit 1"),
        cache_scope=ProcessCacheScope.SUCCESSFUL,
        description="failure",
    )
    result_three = rule_runner.request(FallibleProcessResult, [process])
    result_four = rule_runner.request(FallibleProcessResult, [process])
    rule_runner.new_session("session two")
    result_five = rule_runner.request(FallibleProcessResult, [process])
    assert result_three is result_four
    assert result_four != result_five


def test_cache_scope_per_restart() -> None:
    success_argv = ("/bin/bash", "-c", "echo $RANDOM")
    failure_argv = ("/bin/bash", "-c", "echo $RANDOM; exit 1")

    always_cache_success = Process(
        success_argv, cache_scope=ProcessCacheScope.PER_RESTART_ALWAYS, description="foo"
    )
    always_cache_failure = Process(
        failure_argv, cache_scope=ProcessCacheScope.PER_RESTART_ALWAYS, description="foo"
    )
    success_cache_success = Process(
        success_argv, cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL, description="foo"
    )
    success_cache_failure = Process(
        failure_argv, cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL, description="foo"
    )

    runner_one = new_rule_runner()

    def run(process: Process) -> FallibleProcessResult:
        return runner_one.request(FallibleProcessResult, [process])

    always_cache_success_res1 = run(always_cache_success)
    always_cache_failure_res1 = run(always_cache_failure)
    success_cache_success_res1 = run(success_cache_success)
    success_cache_failure_res1 = run(success_cache_failure)

    runner_one.new_session("new session")
    always_cache_success_res2 = run(always_cache_success)
    always_cache_failure_res2 = run(always_cache_failure)
    success_cache_success_res2 = run(success_cache_success)
    success_cache_failure_res2 = run(success_cache_failure)

    # Even with a new session, most results should be memoized.
    assert always_cache_success_res1 is always_cache_success_res2
    assert always_cache_failure_res1 is always_cache_failure_res2
    assert success_cache_success_res1 is success_cache_success_res2
    assert success_cache_failure_res1 != success_cache_failure_res2

    # But a new scheduler removes all memoization. We do not cache to disk.
    runner_two = new_rule_runner()

    def run(process: Process) -> FallibleProcessResult:
        return runner_two.request(FallibleProcessResult, [process])

    assert run(always_cache_success) != always_cache_success_res1
    assert run(always_cache_failure) != always_cache_failure_res1
    assert run(success_cache_success) != success_cache_success_res1
    assert run(success_cache_failure) != success_cache_failure_res1


def test_cache_scope_never(rule_runner: RuleRunner) -> None:
    process = Process(
        argv=("/bin/bash", "-c", "echo $RANDOM"),
        cache_scope=ProcessCacheScope.NEVER,
        description="random",
    )
    result_one = rule_runner.request(FallibleProcessResult, [process])
    rule_runner.new_session("next attempt")
    result_two = rule_runner.request(FallibleProcessResult, [process])
    # Should re-run in a new Session.
    assert result_one.stdout != result_two.stdout


# TODO: Move to fs_test.py.
def test_create_files(rule_runner: RuleRunner) -> None:
    files = [FileContent("a.txt", b"hello"), FileContent("somedir/b.txt", b"goodbye")]
    digest = rule_runner.request(
        Digest,
        [CreateDigest(files)],
    )

    process = Process(
        argv=("/bin/cat", "a.txt", "somedir/b.txt"),
        input_digest=digest,
        description="",
    )
    result = rule_runner.request(ProcessResult, [process])
    assert result.stdout == b"hellogoodbye"


def test_interactive_process_cannot_have_input_files_and_workspace() -> None:
    mock_digest = Digest(EMPTY_DIGEST.fingerprint, 1)
    with pytest.raises(ValueError):
        InteractiveProcess(argv=["/bin/echo"], input_digest=mock_digest, run_in_workspace=True)


def test_find_binary_non_existent(rule_runner: RuleRunner) -> None:
    with temporary_dir() as tmpdir:
        search_path = [tmpdir]
        binary_paths = rule_runner.request(
            BinaryPaths, [BinaryPathRequest(binary_name="anybin", search_path=search_path)]
        )
        assert binary_paths.first_path is None


def test_find_binary_on_path_without_bash(rule_runner: RuleRunner) -> None:
    # Test that locating a binary on a PATH which does not include bash works (by recursing to
    # locate bash first).
    binary_name = "mybin"
    binary_dir = "bin"
    with temporary_dir() as tmpdir:
        binary_dir_abs = os.path.join(tmpdir, binary_dir)
        binary_path_abs = os.path.join(binary_dir_abs, binary_name)
        safe_mkdir(binary_dir_abs)
        touch(binary_path_abs)

        search_path = [binary_dir_abs]
        binary_paths = rule_runner.request(
            BinaryPaths, [BinaryPathRequest(binary_name=binary_name, search_path=search_path)]
        )
        assert os.path.exists(os.path.join(binary_dir_abs, binary_name))
        assert binary_paths.first_path is not None
        assert binary_paths.first_path.path == binary_path_abs
