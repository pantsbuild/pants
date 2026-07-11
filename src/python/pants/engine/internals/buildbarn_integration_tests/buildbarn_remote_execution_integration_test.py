# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from pants.base.specs import Specs
from pants.engine.fs import CreateDigest, Digest, DigestContents, Directory, FileDigest
from pants.engine.internals.buildbarn_integration_tests.stack import (
    LocalBuildbarnStack,
    RemoteExecutionBuildbarn,
)
from pants.engine.internals.engine_testutil import WorkunitTracker
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.engine.streaming_workunit_handler import StreamingWorkunitHandler
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class RemoteExecutionRun:
    contents: dict[str, bytes]
    output_digest: Digest
    metrics: dict[str, int]
    process_workunit: dict
    remote_action_digest: FileDigest
    remote_command_digest: FileDigest


def _docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    result = subprocess.run(
        [docker, "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _should_skip_for_missing_docker() -> bool:
    return "CI" not in os.environ and not _docker_available()


pytestmark = pytest.mark.skipif(
    _should_skip_for_missing_docker(), reason="Docker is required for Buildbarn tests"
)


def _remote_execution_args(buildbarn: RemoteExecutionBuildbarn) -> list[str]:
    return [
        "--remote-execution",
        "--remote-cache-read",
        "--remote-cache-write",
        f"--remote-store-address={buildbarn.address}",
        f"--remote-execution-address={buildbarn.address}",
        f"--remote-instance-name={buildbarn.instance_name}",
        *[
            f"--remote-execution-extra-platform-properties={property_}"
            for property_ in buildbarn.platform_properties
        ],
    ]


def _new_run_tracker() -> RunTracker:
    ob = create_options_bootstrapper([])
    return RunTracker(ob.args, ob.bootstrap_options)


def _run_remote_process(
    process_input: Process | Callable[[RuleRunner], Process],
    *,
    buildbarn: RemoteExecutionBuildbarn,
) -> RemoteExecutionRun:
    rule_runner = RuleRunner(
        rules=[
            QueryRule(ProcessResult, [Process]),
            QueryRule(DigestContents, [Digest]),
        ],
        isolated_local_store=True,
        max_workunit_verbosity=LogLevel.TRACE,
        bootstrap_args=[
            "--cache-content-behavior=defer",
            "--no-local-cache",
            *_remote_execution_args(buildbarn),
        ],
    )
    process = process_input if isinstance(process_input, Process) else process_input(rule_runner)
    tracker = WorkunitTracker()
    with rule_runner.pushd():
        handler = StreamingWorkunitHandler(
            rule_runner.scheduler,
            run_tracker=_new_run_tracker(),
            callbacks=[tracker],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.DEBUG,
            specs=Specs.empty(),
            options_bootstrapper=create_options_bootstrapper([]),
            allow_async_completion=False,
        )

        with handler:
            result = rule_runner.request(ProcessResult, [process])
            contents = rule_runner.request(DigestContents, [result.output_digest])

    work_units = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
    process_workunits = [wu for wu in work_units if wu.get("name") == "process"]
    assert len(process_workunits) == 1
    process_workunit = process_workunits[0]

    remote_action_digest = process_workunit["artifacts"]["remote_action_digest"]
    remote_command_digest = process_workunit["artifacts"]["remote_command_digest"]
    assert isinstance(remote_action_digest, FileDigest)
    assert isinstance(remote_command_digest, FileDigest)

    return RemoteExecutionRun(
        contents={file_content.path: file_content.content for file_content in contents},
        output_digest=result.output_digest,
        metrics=rule_runner.scheduler.get_metrics(),
        process_workunit=process_workunit,
        remote_action_digest=remote_action_digest,
        remote_command_digest=remote_command_digest,
    )


def _working_directory_process(rule_runner: RuleRunner) -> Process:
    input_digest = rule_runner.request(Digest, [CreateDigest([Directory("workdir")])])
    return Process(
        [
            "/bin/sh",
            "-c",
            "/bin/echo workdir-root > root.txt && /bin/mkdir -p sub && /bin/echo workdir-child > sub/child.txt",
        ],
        description="Buildbarn remote execution working directory output case",
        input_digest=input_digest,
        working_directory="workdir",
        output_directories=[""],
        level=LogLevel.INFO,
    )


def _assert_output_cache_roundtrip(
    process_input: Process | Callable[[RuleRunner], Process],
    expected_contents: dict[str, bytes],
    *,
    buildbarn: RemoteExecutionBuildbarn,
) -> None:
    run1 = _run_remote_process(process_input, buildbarn=buildbarn)

    assert run1.contents == expected_contents
    assert run1.metrics.get("remote_execution_requests", 0) == 1
    assert "backtrack_attempts" not in run1.metrics
    assert len(run1.remote_action_digest.fingerprint) == 64
    assert len(run1.remote_command_digest.fingerprint) == 64
    assert run1.process_workunit["metadata"]["exit_code"] == 0

    run2 = _run_remote_process(process_input, buildbarn=buildbarn)

    assert run2.contents == expected_contents
    assert run2.output_digest == run1.output_digest
    assert run2.metrics.get("remote_execution_requests", 0) == 0
    assert run2.metrics.get("remote_cache_requests_cached", 0) == 1
    assert "backtrack_attempts" not in run2.metrics
    assert run2.remote_action_digest == run1.remote_action_digest
    assert run2.remote_command_digest == run1.remote_command_digest
    assert run2.process_workunit["metadata"]["exit_code"] == 0


def _worker_preflight(buildbarn: RemoteExecutionBuildbarn) -> None:
    preflight_process = Process(
        [
            "/bin/sh",
            "-c",
            "/bin/echo preflight >/dev/null",
        ],
        description="Buildbarn worker preflight",
        level=LogLevel.INFO,
    )
    run = _run_remote_process(preflight_process, buildbarn=buildbarn)
    assert run.contents == {}
    assert run.metrics.get("remote_execution_requests", 0) == 1
    assert run.process_workunit["metadata"]["exit_code"] == 0


@contextmanager
def local_buildbarn_remote_execution() -> Iterator[RemoteExecutionBuildbarn]:
    stack = LocalBuildbarnStack()
    try:
        buildbarn = stack.launch_remote_execution()
        _worker_preflight(buildbarn)
        yield buildbarn
    finally:
        stack.teardown()


def test_buildbarn_remote_execution(subtests) -> None:
    with local_buildbarn_remote_execution() as buildbarn:
        with subtests.test("control process"):
            process = Process(
                [
                    "/bin/sh",
                    "-c",
                    "/bin/true",
                ],
                description="Buildbarn remote execution control case",
                level=LogLevel.INFO,
            )
            run = _run_remote_process(process, buildbarn=buildbarn)

            assert run.contents == {}
            assert run.metrics.get("remote_execution_requests", 0) == 1
            assert len(run.remote_action_digest.fingerprint) == 64
            assert len(run.remote_command_digest.fingerprint) == 64
            assert run.process_workunit["metadata"]["exit_code"] == 0

        with subtests.test('root output directory (".")'):
            expected_contents = {
                "root.txt": b"root\n",
                "sub/child.txt": b"child\n",
            }
            process = Process(
                [
                    "/bin/sh",
                    "-c",
                    "/bin/echo root > root.txt && /bin/mkdir -p sub && /bin/echo child > sub/child.txt",
                ],
                description="Buildbarn remote execution root output case",
                output_directories=["."],
                level=LogLevel.INFO,
            )
            _assert_output_cache_roundtrip(process, expected_contents, buildbarn=buildbarn)

        with subtests.test('working directory output directory ("")'):
            _assert_output_cache_roundtrip(
                _working_directory_process,
                {
                    "root.txt": b"workdir-root\n",
                    "sub/child.txt": b"workdir-child\n",
                },
                buildbarn=buildbarn,
            )
