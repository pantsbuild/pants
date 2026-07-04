# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from pants.engine.internals.buildbarn_integration_tests import stack as buildbarn


def completed_process(
    args: Sequence[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_parse_image_reference_requires_digest() -> None:
    with pytest.raises(buildbarn.FetchError, match="sha256 digest"):
        buildbarn.parse_image_reference("ghcr.io/example/image:latest")


def test_stack_fails_when_manifest_lacks_storage_image(tmp_path: Path) -> None:
    manifest_path = tmp_path / "images.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "images": [
                    {
                        "name": "bb-worker",
                        "reference": f"ghcr.io/buildbarn/bb-worker:latest@sha256:{'d' * 64}",
                        "required_for": ["remote-execution"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    stack = buildbarn.LocalBuildbarnStack(manifest_path=manifest_path, temp_dir=tmp_path)

    with pytest.raises(buildbarn.FetchError, match="bb-storage"):
        stack.launch_cache_only()


def test_prepare_remote_execution_dirs_creates_expected_paths(tmp_path: Path) -> None:
    buildbarn._prepare_remote_execution_dirs(tmp_path)

    expected_paths = [
        tmp_path / "storage-cas" / "persistent_state",
        tmp_path / "storage-ac" / "persistent_state",
        tmp_path / "storage-fsac" / "persistent_state",
        tmp_path / "worker" / "build",
        tmp_path / "worker" / "cache",
        tmp_path / "bb",
    ]
    assert all(path.exists() for path in expected_paths)


def test_write_runtime_overlay_uses_instance_name(tmp_path: Path) -> None:
    overlay_path = tmp_path / "runtime.libsonnet"

    buildbarn._write_runtime_overlay(
        overlay_path,
        instance_name="pants-test",
        execution_image_reference="ghcr.io/example/executor:tag@sha256:" + "e" * 64,
    )

    overlay = overlay_path.read_text(encoding="utf-8")
    assert '"pants-test"' in overlay
    assert "ghcr.io/example/executor:tag@sha256:" in overlay


def test_write_compose_logs_uses_compose_command(tmp_path: Path) -> None:
    commands: list[tuple[tuple[str, ...], bool]] = []

    def run_command(args: Sequence[str], check: bool) -> subprocess.CompletedProcess[str]:
        commands.append((tuple(args), check))
        return completed_process(args, stdout="service log\n")

    stack = buildbarn.LocalBuildbarnStack(temp_dir=tmp_path, run_command=run_command)
    stack._project_name = "pants-buildbarn-test"
    stack._runtime_root = tmp_path
    stack._env_file = tmp_path / "compose.env"
    stack._compose_file = tmp_path / "docker-compose.yaml"
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    buildbarn._write_compose_logs(stack)

    assert (tmp_path / "logs" / "compose.log").read_text(encoding="utf-8") == "service log\n"
    assert commands == [
        (
            (
                "docker",
                "compose",
                "--project-name",
                "pants-buildbarn-test",
                "--file",
                str(tmp_path / "docker-compose.yaml"),
                "--env-file",
                str(tmp_path / "compose.env"),
                "logs",
                "--no-color",
                "--timestamps",
            ),
            False,
        )
    ]
