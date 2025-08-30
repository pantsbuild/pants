# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import time

import pytest

from pants.base.specs import Specs
from pants.core.util_rules import distdir
from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import Digest, DigestContents, DigestEntries, FileDigest, FileEntry, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.engine_testutil import WorkunitTracker
from pants.engine.internals.native_engine import EMPTY_FILE_DIGEST, PyExecutor, PyStubCAS
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, goal_rule, rule
from pants.engine.streaming_workunit_handler import StreamingWorkunitHandler
from pants.goal.run_tracker import RunTracker
from pants.option.bootstrap_options import CacheContentBehavior, RemoteCacheWarningsBehavior
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.pants_integration_test import run_pants
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.logging import LogLevel


def remote_cache_args(
    store_address: str,
    warnings_behavior: RemoteCacheWarningsBehavior = RemoteCacheWarningsBehavior.backoff,
) -> list[str]:
    # NB: Our options code expects `grpc://`, which it will then convert back to
    # `http://` before sending over FFI.
    store_address = store_address.replace("http://", "grpc://")
    return [
        "--remote-cache-read",
        "--remote-cache-write",
        f"--remote-cache-warnings={warnings_behavior.value}",
        f"--remote-store-address={store_address}",
    ]


def test_warns_on_remote_cache_errors() -> None:
    executor = PyExecutor(core_threads=2, max_threads=4)
    cas = PyStubCAS.builder().ac_always_errors().cas_always_errors().build(executor)

    def run(behavior: RemoteCacheWarningsBehavior) -> str:
        pants_run = run_pants(
            [
                "--backend-packages=['pants.backend.experimental.java']",
                "--no-dynamic-ui",
                "--no-local-cache",
                *remote_cache_args(cas.address, behavior),
                "check",
                "testprojects/src/jvm/org/pantsbuild/example/lib/ExampleLib.java",
            ],
        )
        pants_run.assert_success()
        return pants_run.stderr

    def read_err(i: int) -> str:
        return f"Failed to read from remote cache ({i} occurrences so far): Unavailable"

    def write_err(i: int) -> str:
        return (
            f'Failed to write to remote cache ({i} occurrences so far): Internal: "StubCAS is '
            f'configured to always fail"'
        )

    first_read_err = read_err(1)
    first_write_err = write_err(1)
    third_read_err = read_err(3)
    third_write_err = write_err(3)
    fourth_read_err = read_err(4)
    fourth_write_err = write_err(4)

    # Generate lock files first, as the test is java test.
    pants_run = run_pants(
        [
            "--backend-packages=['pants.backend.experimental.java']",
            "--no-dynamic-ui",
            "--no-local-cache",
            "generate-lockfiles",
        ],
    )
    pants_run.assert_success()

    ignore_result = run(RemoteCacheWarningsBehavior.ignore)
    for err in [
        first_read_err,
        first_write_err,
        third_read_err,
        third_write_err,
        fourth_read_err,
        fourth_write_err,
    ]:
        assert err not in ignore_result

    first_only_result = run(RemoteCacheWarningsBehavior.first_only)
    for err in [first_read_err, first_write_err]:
        assert err in first_only_result, f"Not found in:\n{first_only_result}"
    for err in [third_read_err, third_write_err, fourth_read_err, fourth_write_err]:
        assert err not in first_only_result

    backoff_result = run(RemoteCacheWarningsBehavior.backoff)
    for err in [first_read_err, first_write_err, fourth_read_err, fourth_write_err]:
        assert err in backoff_result, f"Not found in:\n{backoff_result}"
    for err in [third_read_err, third_write_err]:
        assert err not in backoff_result

    always_result = run(RemoteCacheWarningsBehavior.always)
    for err in [
        first_read_err,
        first_write_err,
        third_read_err,
        third_write_err,
        fourth_read_err,
        fourth_write_err,
    ]:
        assert err in always_result, f"Not found in:\n{always_result}"


class ProcessOutputEntries(DigestEntries):
    pass


@rule
async def entries_from_process(process_result: ProcessResult) -> ProcessOutputEntries:
    # DigestEntries won't actually load file content, so we need to force it with DigestContents.
    _ = await Get(DigestContents, Digest, process_result.output_digest)
    return ProcessOutputEntries(await Get(DigestEntries, Digest, process_result.output_digest))


def test_async_backtracking() -> None:
    """Tests that we backtrack when a MissingDigest error occurs at a `@rule` (async) boundary."""
    executor = PyExecutor(core_threads=2, max_threads=4)
    cas = PyStubCAS.builder().build(executor)

    def run() -> tuple[FileDigest, dict[str, int]]:
        # Use an isolated store to ensure that the only content is in the remote/stub cache.
        rule_runner = RuleRunner(
            rules=[entries_from_process, QueryRule(ProcessOutputEntries, [Process])],
            isolated_local_store=True,
            bootstrap_args=[
                "--cache-content-behavior=defer",
                "--no-local-cache",
                *remote_cache_args(cas.address),
            ],
        )
        entries = rule_runner.request(
            ProcessOutputEntries,
            [
                Process(
                    ["/bin/bash", "-c", "/bin/sleep 1 && echo content > file.txt"],
                    description="Create file.txt",
                    output_files=["file.txt"],
                    level=LogLevel.INFO,
                )
            ],
        )
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, FileEntry)

        # Wait for any async cache writes to complete.
        time.sleep(1)
        return entry.file_digest, rule_runner.scheduler.get_metrics()

    # Run once to populate the remote cache, and validate that there is one entry afterwards.
    assert cas.action_cache_len() == 0
    file_digest1, metrics1 = run()
    assert cas.action_cache_len() == 1
    assert metrics1["remote_cache_requests"] == 1
    assert metrics1["remote_cache_requests_uncached"] == 1

    # Confirm that we can hit the cache.
    file_digest2, metrics2 = run()
    assert file_digest1 == file_digest2
    assert metrics2["remote_cache_requests"] == 1
    assert metrics2["remote_cache_requests_cached"] == 1
    assert "backtrack_attempts" not in metrics2

    # Then, remove the content from the remote store and run again.
    assert cas.remove(file_digest1)
    file_digest3, metrics3 = run()
    assert file_digest1 == file_digest3
    # Validate both that we hit the cache, and that we backtracked to actually run the process.
    assert metrics3["remote_cache_requests"] == 1
    assert metrics3["remote_cache_requests_cached"] == 1
    assert metrics3["backtrack_attempts"] == 1


class MockRunSubsystem(GoalSubsystem):
    name = "mock-run"
    help = "Run a simple process and write its output to the dist dir."


class MockRun(Goal):
    subsystem_cls = MockRunSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def mock_run(workspace: Workspace, dist_dir: DistDir, mock_run: MockRunSubsystem) -> MockRun:
    result = await Get(
        ProcessResult,
        Process(
            ["/bin/bash", "-c", "/bin/sleep 1 && echo content > file.txt"],
            description="Create file.txt",
            output_files=["file.txt"],
            level=LogLevel.INFO,
        ),
    )
    workspace.write_digest(
        result.output_digest,
        path_prefix=str(dist_dir.relpath),
        side_effecting=False,
    )
    return MockRun(exit_code=0)


def test_sync_backtracking() -> None:
    """Tests that we backtrack when a MissingDigest error occurs synchronously (in write_digest)."""
    executor = PyExecutor(core_threads=2, max_threads=4)
    cas = PyStubCAS.builder().build(executor)

    def run() -> dict[str, int]:
        # Use an isolated store to ensure that the only content is in the remote/stub cache.
        rule_runner = RuleRunner(
            rules=[mock_run, *distdir.rules(), *MockRunSubsystem.rules()],
            isolated_local_store=True,
            bootstrap_args=[
                "--cache-content-behavior=defer",
                "--no-local-cache",
                *remote_cache_args(cas.address),
            ],
        )
        result = rule_runner.run_goal_rule(MockRun, args=[])
        assert result.exit_code == 0

        # Wait for any async cache writes to complete.
        time.sleep(1)
        return rule_runner.scheduler.get_metrics()

    # Run once to populate the remote cache, and validate that there is one entry afterwards.
    assert cas.action_cache_len() == 0
    metrics1 = run()
    assert cas.action_cache_len() == 1
    assert metrics1["remote_cache_requests"] == 1
    assert metrics1["remote_cache_requests_uncached"] == 1

    # Then, remove the content from the remote store and run again.
    assert cas.remove(
        FileDigest("434728a410a78f56fc1b5899c3593436e61ab0c731e9072d95e96db290205e53", 8)
    )
    metrics2 = run()
    # Validate both that we hit the cache, and that we backtracked to actually run the process.
    assert metrics2["remote_cache_requests"] == 1
    assert metrics2["remote_cache_requests_cached"] == 1
    assert metrics2["backtrack_attempts"] == 1


@pytest.mark.parametrize(
    "cache_content_behavior", [CacheContentBehavior.validate, CacheContentBehavior.fetch]
)
def test_eager_validation(cache_content_behavior: CacheContentBehavior) -> None:
    """Tests that --cache-content-behavior={validate,fetch} fail a lookup for missing content."""
    executor = PyExecutor(core_threads=2, max_threads=4)
    cas = PyStubCAS.builder().build(executor)

    def run() -> dict[str, int]:
        # Use an isolated store to ensure that the only content is in the remote/stub cache.
        rule_runner = RuleRunner(
            rules=[mock_run, *distdir.rules(), *MockRunSubsystem.rules()],
            isolated_local_store=True,
            bootstrap_args=[
                f"--cache-content-behavior={cache_content_behavior.value}",
                "--no-local-cache",
                *remote_cache_args(cas.address),
            ],
        )
        result = rule_runner.run_goal_rule(MockRun, args=[])
        assert result.exit_code == 0

        # Wait for any async cache writes to complete.
        time.sleep(1)
        return rule_runner.scheduler.get_metrics()

    # Run once to populate the remote cache, and validate that there is one entry afterwards.
    assert cas.action_cache_len() == 0
    metrics1 = run()
    assert cas.action_cache_len() == 1
    assert metrics1["remote_cache_requests"] == 1
    assert metrics1["remote_cache_requests_uncached"] == 1

    # Ensure that we can hit the cache.
    metrics2 = run()
    assert metrics2["remote_cache_requests"] == 1
    assert metrics2["remote_cache_requests_cached"] == 1
    assert "backtrack_attempts" not in metrics2

    # Then, remove the content from the remote store and run again.
    assert cas.remove(
        FileDigest("434728a410a78f56fc1b5899c3593436e61ab0c731e9072d95e96db290205e53", 8)
    )
    metrics3 = run()
    # Validate that we missed the cache, and that we didn't backtrack.
    assert metrics3["remote_cache_requests"] == 1
    assert metrics3["remote_cache_requests_uncached"] == 1
    assert "backtrack_attempts" not in metrics3


@pytest.mark.skip(reason="Flaky test which needs to be reevaluated.")
@pytest.mark.no_error_if_skipped
def test_remote_cache_workunits() -> None:
    """Tests that remote cache operations properly emit workunits with metadata."""
    executor = PyExecutor(core_threads=2, max_threads=4)
    cas = PyStubCAS.builder().build(executor)

    def create_handler():
        rule_runner = RuleRunner(
            rules=[
                QueryRule(ProcessResult, [Process]),
                QueryRule(DigestContents, [Digest]),
            ],
            isolated_local_store=True,
            max_workunit_verbosity=LogLevel.TRACE,
            bootstrap_args=[
                "--cache-content-behavior=validate",
                "--no-local-cache",
                *remote_cache_args(cas.address),
            ],
        )

        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            rule_runner.scheduler,
            run_tracker=new_run_tracker(),
            callbacks=[tracker],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.DEBUG,
            specs=Specs.empty(),
            options_bootstrapper=create_options_bootstrapper([]),
            allow_async_completion=False,
        )
        return rule_runner, tracker, handler

    def run_process():
        test_process = Process(
            argv=["/bin/bash", "-c", "echo 'test content' > output.txt"],
            description="Create test output",
            output_files=["output.txt"],
            level=LogLevel.INFO,
        )

        rule_runner, tracker, handler = create_handler()
        with handler:
            result = rule_runner.request(ProcessResult, [test_process])

            # Verify the process actually created the file
            contents = rule_runner.request(DigestContents, [result.output_digest])
            assert len(contents) == 1
            assert contents[0].path == "output.txt"
            assert contents[0].content == b"test content\n"

            # Wait for any async cache writes to complete
            time.sleep(1)

        work_units = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        process_workunits = [wu for wu in work_units if wu.get("name") == "process"]
        assert len(process_workunits) == 1
        process_unit = process_workunits[0]

        assert process_unit["name"] == "process"
        assert process_unit["description"] == "Scheduling: Create test output"
        assert process_unit["metadata"]["exit_code"] == 0

        remote_action_digest = process_unit["artifacts"]["remote_action_digest"]
        remote_command_digest = process_unit["artifacts"]["remote_command_digest"]

        assert isinstance(remote_action_digest, FileDigest)
        assert len(remote_action_digest.fingerprint) == 64, (
            "Action digest should be a 64-character hash"
        )
        assert isinstance(remote_command_digest, FileDigest)
        assert len(remote_command_digest.fingerprint) == 64, (
            "Command digest should be a 64-character hash"
        )

        assert process_unit["artifacts"]["stdout_digest"] == EMPTY_FILE_DIGEST
        assert process_unit["artifacts"]["stderr_digest"] == EMPTY_FILE_DIGEST
        return process_unit, remote_action_digest, remote_command_digest

    # First run should miss cache and populate it
    process_unit, action_digest, command_digest = run_process()
    assert process_unit["metadata"]["source"] == "Ran"

    # Verify the action and command digests are in the CAS and the action result is in the Action Cache.
    loops_remaining_to_check = 8
    while loops_remaining_to_check > 0:
        time.sleep(0.25)  # wait for CAS/AC to receive data
        cas_has_action_digest = cas.contains(action_digest)
        cas_has_command_digest = cas.contains(command_digest)
        ac_has_action_result = cas.contains_action_result(action_digest)
        if cas_has_action_digest and cas_has_command_digest and ac_has_action_result:
            break
        loops_remaining_to_check -= 1

    assert cas_has_action_digest, "Action digest should be in the CAS"
    assert cas_has_command_digest, "Command digest should be in the CAS"
    assert ac_has_action_result, "Action result should be in the Action Cache"

    # Second run should hit cache
    process_unit2, action_digest2, command_digest2 = run_process()
    assert process_unit2["metadata"]["source"] == "HitRemotely"
    assert action_digest == action_digest2
    assert command_digest == command_digest2


def new_run_tracker() -> RunTracker:
    ob = create_options_bootstrapper([])
    return RunTracker(ob.args, ob.bootstrap_options)
