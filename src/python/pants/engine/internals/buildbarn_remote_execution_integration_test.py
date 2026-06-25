# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from contextlib import contextmanager
from dataclasses import dataclass
import os
import shutil
import subprocess

import launch as buildbarn_launch
import pytest

from pants.base.specs import Specs
from pants.engine.fs import Digest, DigestContents, FileDigest
from pants.engine.internals.engine_testutil import WorkunitTracker
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.engine.streaming_workunit_handler import StreamingWorkunitHandler
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel


DEFAULT_INSTANCE_NAME = "fuse"


@dataclass(frozen=True)
class BuildbarnExecutionAddress:
    address: str
    instance_name: str
    platform_properties: tuple[str, ...]


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


pytestmark = pytest.mark.skipif(not _docker_available(), reason="Docker is required for Buildbarn tests")


def _extra_platform_properties() -> tuple[str, ...]:
    raw = os.environ.get("PANTS_BUILDBARN_EXTRA_PLATFORM_PROPERTIES", "")
    if not raw.strip():
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _remote_execution_args(buildbarn: BuildbarnExecutionAddress) -> list[str]:
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
    process: Process,
    *,
    buildbarn: BuildbarnExecutionAddress,
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


def _worker_preflight(buildbarn: BuildbarnExecutionAddress) -> None:
    preflight_process = Process(
        [
            "/bin/sh",
            "-c",
            "/bin/mkdir -p preflight && /bin/echo ok > preflight/result.txt",
        ],
        description="Buildbarn worker preflight",
        output_directories=["preflight"],
        level=LogLevel.INFO,
    )
    run = _run_remote_process(preflight_process, buildbarn=buildbarn)
    assert run.contents == {"preflight/result.txt": b"ok\n"}


@contextmanager
def buildbarn_remote_execution_address() -> BuildbarnExecutionAddress:
    existing_address = os.environ.get("PANTS_BUILDBARN_ADDRESS")
    instance_name = os.environ.get("PANTS_BUILDBARN_INSTANCE_NAME", DEFAULT_INSTANCE_NAME)
    extra_platform_properties = _extra_platform_properties()
    if existing_address:
        buildbarn = BuildbarnExecutionAddress(
            address=existing_address,
            instance_name=instance_name,
            platform_properties=extra_platform_properties,
        )
        _worker_preflight(buildbarn)
        yield buildbarn
        return

    launcher = buildbarn_launch.BuildbarnLauncher(instance_name=instance_name)
    try:
        instance = launcher.launch_remote_execution()
        buildbarn = BuildbarnExecutionAddress(
            address=instance.address,
            instance_name=instance.instance_name,
            platform_properties=instance.platform_properties + extra_platform_properties,
        )
        _worker_preflight(buildbarn)
        yield buildbarn
    finally:
        launcher.teardown()


def test_buildbarn_remote_execution_non_root_output_directory() -> None:
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
        description="Buildbarn remote execution control case",
        output_files=["root.txt"],
        output_directories=["sub"],
        level=LogLevel.INFO,
    )

    with buildbarn_remote_execution_address() as buildbarn:
        run = _run_remote_process(process, buildbarn=buildbarn)

    assert run.contents == expected_contents
    assert run.metrics.get("remote_execution_requests", 0) == 1
    assert len(run.remote_action_digest.fingerprint) == 64
    assert len(run.remote_command_digest.fingerprint) == 64
    assert run.process_workunit["metadata"]["exit_code"] == 0


def test_buildbarn_remote_execution_root_output_directory() -> None:
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

    with buildbarn_remote_execution_address() as buildbarn:
        run = _run_remote_process(process, buildbarn=buildbarn)

    assert run.contents == expected_contents
    assert run.metrics.get("remote_execution_requests", 0) == 1
    assert len(run.remote_action_digest.fingerprint) == 64
    assert len(run.remote_command_digest.fingerprint) == 64
    assert run.process_workunit["metadata"]["exit_code"] == 0
