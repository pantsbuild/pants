# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.buildbarn_integration_tests.stack import LocalBuildbarnStack
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel


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


def _remote_cache_args(address: str, instance_name: str) -> list[str]:
    return [
        "--remote-cache-read",
        "--remote-cache-write",
        f"--remote-store-address={address}",
        f"--remote-instance-name={instance_name}",
    ]


def _run_process(
    process: Process, *, address: str, instance_name: str
) -> tuple[dict[str, bytes], Digest, dict[str, int]]:
    rule_runner = RuleRunner(
        rules=[
            QueryRule(ProcessResult, [Process]),
            QueryRule(DigestContents, [Digest]),
        ],
        isolated_local_store=True,
        bootstrap_args=[
            "--cache-content-behavior=defer",
            "--no-local-cache",
            *_remote_cache_args(address, instance_name),
        ],
    )

    result = rule_runner.request(ProcessResult, [process])
    contents = rule_runner.request(DigestContents, [result.output_digest])

    # Wait for async cache writes to land before starting the next fresh runner.
    time.sleep(1)
    return (
        {file_content.path: file_content.content for file_content in contents},
        result.output_digest,
        rule_runner.scheduler.get_metrics(),
    )


def test_buildbarn_remote_cache_roundtrips_file_and_directory_outputs() -> None:
    expected_contents = {
        "file.txt": b"file-output\n",
        "out/nested.txt": b"nested-output\n",
    }
    process = Process(
        [
            "/bin/sh",
            "-c",
            "/bin/echo file-output > file.txt && /bin/mkdir -p out && /bin/echo nested-output > out/nested.txt",
        ],
        description="Create file and directory outputs",
        output_files=["file.txt"],
        output_directories=["out"],
        level=LogLevel.INFO,
    )

    with LocalBuildbarnStack() as buildbarn:
        contents1, digest1, metrics1 = _run_process(
            process,
            address=buildbarn.address,
            instance_name=buildbarn.instance_name,
        )
        assert contents1 == expected_contents
        assert metrics1["remote_cache_requests"] == 1
        assert metrics1["remote_cache_requests_uncached"] == 1
        assert "backtrack_attempts" not in metrics1

        contents2, digest2, metrics2 = _run_process(
            process,
            address=buildbarn.address,
            instance_name=buildbarn.instance_name,
        )
        assert contents2 == expected_contents
        assert digest1 == digest2
        assert metrics2["remote_cache_requests"] == 1
        assert metrics2["remote_cache_requests_cached"] == 1
        assert "backtrack_attempts" not in metrics2


def test_buildbarn_remote_cache_roundtrips_root_output_directory() -> None:
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
        description="Create root output directory contents",
        output_directories=["."],
        level=LogLevel.INFO,
    )

    with LocalBuildbarnStack() as buildbarn:
        contents1, digest1, metrics1 = _run_process(
            process,
            address=buildbarn.address,
            instance_name=buildbarn.instance_name,
        )
        assert contents1 == expected_contents
        assert metrics1["remote_cache_requests"] == 1
        assert metrics1["remote_cache_requests_uncached"] == 1
        assert "backtrack_attempts" not in metrics1

        contents2, digest2, metrics2 = _run_process(
            process,
            address=buildbarn.address,
            instance_name=buildbarn.instance_name,
        )
        assert contents2 == expected_contents
        assert digest1 == digest2
        assert metrics2["remote_cache_requests"] == 1
        assert metrics2["remote_cache_requests_cached"] == 1
        assert "backtrack_attempts" not in metrics2


def test_buildbarn_remote_cache_roundtrips_empty_root_output_directory() -> None:
    expected_contents = {
        "root.txt": b"empty-root\n",
        "sub/child.txt": b"empty-child\n",
    }
    process = Process(
        [
            "/bin/sh",
            "-c",
            "/bin/echo empty-root > root.txt && /bin/mkdir -p sub && /bin/echo empty-child > sub/child.txt",
        ],
        description="Create empty root output directory contents",
        output_directories=[""],
        level=LogLevel.INFO,
    )

    with LocalBuildbarnStack() as buildbarn:
        contents1, digest1, metrics1 = _run_process(
            process,
            address=buildbarn.address,
            instance_name=buildbarn.instance_name,
        )
        assert contents1 == expected_contents
        assert metrics1["remote_cache_requests"] == 1
        assert metrics1["remote_cache_requests_uncached"] == 1
        assert "backtrack_attempts" not in metrics1

        contents2, digest2, metrics2 = _run_process(
            process,
            address=buildbarn.address,
            instance_name=buildbarn.instance_name,
        )
        assert contents2 == expected_contents
        assert digest1 == digest2
        assert metrics2["remote_cache_requests"] == 1
        assert metrics2["remote_cache_requests_cached"] == 1
        assert "backtrack_attempts" not in metrics2
