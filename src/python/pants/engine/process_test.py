# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pants.engine.environment import LOCAL_WORKSPACE_ENV_NAME, EnvironmentName
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    Directory,
    FileContent,
    SymlinkEntry,
)
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.platform import Platform
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
    ProcessCacheScope,
    ProcessResult,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, mock_console
from pants.util.contextutil import environment_as


def new_rule_runner(**extra_kwargs) -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(ProcessResult, [Process]),
            QueryRule(FallibleProcessResult, [Process]),
            QueryRule(InteractiveProcessResult, [InteractiveProcess]),
            QueryRule(DigestEntries, [Digest]),
            QueryRule(Platform, []),
        ],
        **extra_kwargs,
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


@pytest.mark.parametrize("working_directory", ["", "subdir"])
def test_output_digest(rule_runner: RuleRunner, working_directory) -> None:
    # Test that the output files are relative to the working directory, both in how
    # they're specified, and their paths in the output_digest.
    input_digest = (
        rule_runner.request(
            Digest,
            [CreateDigest([Directory(working_directory)])],
        )
        if working_directory
        else EMPTY_DIGEST
    )
    process = Process(
        input_digest=input_digest,
        argv=("/bin/bash", "-c", "echo -n 'European Burmese' > roland"),
        description="echo roland",
        output_files=("roland",),
        working_directory=working_directory,
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
        argv=("/bin/bash", "-c", "/bin/sleep 0.5; /bin/echo -n 'European Burmese'"),
        timeout_seconds=0.1,
        description="sleepy-cat",
    )
    result = rule_runner.request(FallibleProcessResult, [process])
    assert result.exit_code != 0
    assert b"Exceeded timeout" in result.stderr
    assert b"sleepy-cat" in result.stderr


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
    rule_runner.set_options([])
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
    rule_runner.set_options([])
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
    rule_runner.set_options([])
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

    def run1(process: Process) -> FallibleProcessResult:
        return runner_one.request(FallibleProcessResult, [process])

    always_cache_success_res1 = run1(always_cache_success)
    always_cache_failure_res1 = run1(always_cache_failure)
    success_cache_success_res1 = run1(success_cache_success)
    success_cache_failure_res1 = run1(success_cache_failure)

    runner_one.new_session("new session")
    runner_one.set_options([])
    always_cache_success_res2 = run1(always_cache_success)
    always_cache_failure_res2 = run1(always_cache_failure)
    success_cache_success_res2 = run1(success_cache_success)
    success_cache_failure_res2 = run1(success_cache_failure)

    # Even with a new session, most results should be memoized.
    assert always_cache_success_res1 is always_cache_success_res2
    assert always_cache_failure_res1 is always_cache_failure_res2
    assert success_cache_success_res1 is success_cache_success_res2
    assert success_cache_failure_res1 != success_cache_failure_res2

    # But a new scheduler removes all memoization. We do not cache to disk.
    runner_two = new_rule_runner()

    def run2(process: Process) -> FallibleProcessResult:
        return runner_two.request(FallibleProcessResult, [process])

    assert run2(always_cache_success) != always_cache_success_res1
    assert run2(always_cache_failure) != always_cache_failure_res1
    assert run2(success_cache_success) != success_cache_success_res1
    assert run2(success_cache_failure) != success_cache_failure_res1


def test_cache_scope_per_session(rule_runner: RuleRunner) -> None:
    process = Process(
        argv=("/bin/bash", "-c", "echo $RANDOM"),
        cache_scope=ProcessCacheScope.PER_SESSION,
        description="random",
    )
    result_one = rule_runner.request(FallibleProcessResult, [process])
    result_two = rule_runner.request(FallibleProcessResult, [process])
    assert result_one is result_two

    rule_runner.new_session("next attempt")
    rule_runner.set_options([])
    result_three = rule_runner.request(FallibleProcessResult, [process])
    # Should re-run in a new Session.
    assert result_one != result_three


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


def test_process_output_symlink_aware(rule_runner: RuleRunner) -> None:
    process = Process(
        argv=("/bin/ln", "-s", "dest", "source"),
        output_files=["source"],
        description="",
        working_directory="",
    )
    result = rule_runner.request(ProcessResult, [process])
    entries = rule_runner.request(DigestEntries, [result.output_digest])
    assert entries == DigestEntries([SymlinkEntry("source", "dest")])


@pytest.mark.parametrize("run_in_workspace", [True, False])
def test_interactive_process_inputs(rule_runner: RuleRunner, run_in_workspace: bool) -> None:
    digest0 = rule_runner.request(Digest, [CreateDigest([FileContent("file0", b"")])])
    digest1 = rule_runner.request(Digest, [CreateDigest([FileContent("file1", b"")])])
    digest2 = rule_runner.request(
        Digest, [CreateDigest([FileContent("file2", b""), FileContent("file3", b"")])]
    )
    process = InteractiveProcess(
        argv=["/bin/bash", "-c", "ls -1 '{chroot}'"],
        env={"BAZ": "QUX"},
        input_digest=digest0,
        immutable_input_digests={"prefix1": digest1, "prefix2": digest2},
        append_only_caches={"cache_name": "append_only0"},
        run_in_workspace=run_in_workspace,
    )
    with mock_console(rule_runner.options_bootstrapper) as (_, stdio_reader):
        result = rule_runner.run_interactive_process(process)
        assert result.exit_code == 0
        assert set(stdio_reader.get_stdout().splitlines()) == {
            "append_only0",
            "file0",
            "prefix1",
            "prefix2",
        }


def test_workspace_process_basic(rule_runner) -> None:
    rule_runner = new_rule_runner(inherent_environment=EnvironmentName(LOCAL_WORKSPACE_ENV_NAME))
    build_root = Path(rule_runner.build_root)

    # Check that a custom exit code is returned as expected.
    process = Process(
        argv=["/bin/bash", "-c", "exit 143"],
        description="a process which reports its error code",
        cache_scope=ProcessCacheScope.PER_SESSION,  # necessary to ensure result not cached from prior test runs
    )
    result = rule_runner.request(FallibleProcessResult, [process])
    assert result.exit_code == 143
    assert result.metadata.execution_environment.environment_type == "workspace"

    # Test whether there is a distinction between the workspace and chroot when a workspace
    # process executes. Do this by puttng a file in the build root which is not covered by a
    # target, a depenency created via a digest, and have the invoked process create a file
    # in the build root.
    rule_runner.write_files(
        {
            "unmanaged.txt": "from-workspace\n",
        }
    )
    input_snapshot = rule_runner.make_snapshot(
        {
            "dependency.txt": "from-digest\n",
        }
    )
    script = textwrap.dedent(
        """
        cat '{chroot}/dependency.txt'
        pwd
        cat unmanaged.txt
        touch created-by-invocation
        """
    )
    process = Process(
        argv=["/bin/bash", "-c", script],
        input_digest=input_snapshot.digest,
        description="a workspace process",
        cache_scope=ProcessCacheScope.PER_SESSION,  # necessary to ensure result not cached from prior test runs
    )
    result = rule_runner.request(ProcessResult, [process])
    lines = result.stdout.decode().splitlines()
    assert lines == [
        "from-digest",
        rule_runner.build_root,
        "from-workspace",
    ]
    assert (build_root / "created-by-invocation").exists()

    # Test that changing the working directory works.
    subdir = build_root / "subdir"
    subdir.mkdir()
    process = Process(
        argv=["/bin/bash", "-c", "touch file-in-subdir"],
        description="check working_directory works",
        working_directory="subdir",
        cache_scope=ProcessCacheScope.PER_SESSION,  # necessary to ensure result not cached from prior test runs
    )
    result = rule_runner.request(ProcessResult, [process])
    assert (subdir / "file-in-subdir").exists()

    # Test output capture correctly captures from the sandbox and not the workspace.
    script = textwrap.dedent(
        """
        touch '{chroot}/capture-this-file' will-not-capture-this-file
        echo this-goes-to-stdout
        echo this-goes-to-stderr 1>&2
        """
    )
    process = Process(
        argv=["/bin/bash", "-c", script],
        description="check output capture works",
        output_files=["capture-this-file", "will-not-capture-this-file"],
        cache_scope=ProcessCacheScope.PER_SESSION,  # necessary to ensure result not cached from prior test runs
    )
    result = rule_runner.request(ProcessResult, [process])
    assert result.stdout.decode() == "this-goes-to-stdout\n"
    assert result.stderr.decode() == "this-goes-to-stderr\n"
    snapshot = rule_runner.request(Snapshot, [result.output_digest])
    assert snapshot.files == ("capture-this-file",)
