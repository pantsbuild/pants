# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import launch


def completed_process(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_write_cache_only_config_uses_instance_name(tmp_path: Path) -> None:
    config_path = tmp_path / "bb_storage.jsonnet"

    launch._write_cache_only_config(config_path, instance_name="pants-test")

    config = config_path.read_text()
    assert "allowedInstanceNamePrefixes: ['pants-test']" in config
    assert "listenAddresses: [':8980']" in config
    assert "schedulers" not in config


def test_discover_host_port_parses_docker_output() -> None:
    def run_command(args: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        assert args == ["docker", "port", "buildbarn", "8980/tcp"]
        assert check is True
        return completed_process(args, stdout="127.0.0.1:49155\n")

    port = launch._discover_host_port(
        "buildbarn",
        container_port=8980,
        docker_binary="docker",
        run_command=run_command,
    )

    assert port == 49155


def test_launcher_teardown_collects_logs_and_removes_container(tmp_path: Path) -> None:
    commands: list[tuple[tuple[str, ...], bool]] = []

    def run_command(args: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        commands.append((tuple(args), check))
        if args[:3] == ["docker", "logs", "container-1"]:
            return completed_process(args, stdout="hello\n", stderr="world\n")
        if args[:3] == ["docker", "rm", "--force"]:
            return completed_process(args)
        if args[:3] == ["docker", "network", "rm"]:
            return completed_process(args)
        raise AssertionError(f"Unexpected command: {args}")

    launcher = launch.BuildbarnLauncher(temp_dir=tmp_path, run_command=run_command)
    launcher._containers.append(launch.ContainerProcess(name="container-1", image="image"))
    launcher._container_logs["container-1"] = tmp_path / "bb_storage.log"
    launcher._launched = launch.CacheOnlyBuildbarn(
        address="grpc://127.0.0.1:12345",
        instance_name="fuse",
        grpc_port=12345,
        container_name="container-1",
        temp_dir=tmp_path,
        config_path=tmp_path / "bb_storage.jsonnet",
        logs_path=tmp_path / "bb_storage.log",
    )

    launcher.teardown(remove_temp_dir=False)

    assert (tmp_path / "bb_storage.log").read_text() == "hello\nworld\n"
    assert commands == [
        (("docker", "logs", "container-1"), False),
        (("docker", "rm", "--force", "container-1"), False),
    ]


def test_launcher_fails_when_manifest_lacks_storage_image(tmp_path: Path) -> None:
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
        )
    )

    launcher = launch.BuildbarnLauncher(manifest_path=manifest_path, temp_dir=tmp_path)

    with pytest.raises(launch.FetchError, match="bb-storage"):
        launcher.launch_cache_only()


def test_write_remote_execution_frontend_config_routes_to_storage_and_scheduler(tmp_path: Path) -> None:
    config_path = tmp_path / "frontend.jsonnet"

    launch._write_remote_execution_frontend_config(config_path)

    config = config_path.read_text()
    assert "address: 'scheduler:8982'" in config
    assert "address: 'storage:8981'" in config
    assert "executeAuthorizer: { allow: {} }" in config


def test_write_remote_execution_worker_config_uses_instance_prefix_and_execution_image(tmp_path: Path) -> None:
    config_path = tmp_path / "worker.jsonnet"

    launch._write_remote_execution_worker_config(
        config_path,
        instance_name="fuse",
        execution_image_reference="ghcr.io/example/executor:tag@sha256:" + "e" * 64,
    )

    config = config_path.read_text()
    assert "instanceNamePrefix: 'fuse'" in config
    assert "name: 'OSFamily', value: 'linux'" in config
    assert "container-image', value: 'docker://ghcr.io/example/executor:tag@sha256:" in config


def test_prepare_remote_execution_dirs_creates_expected_paths(tmp_path: Path) -> None:
    launch._prepare_remote_execution_dirs(tmp_path)

    expected_paths = [
        tmp_path / "storage-cas" / "persistent_state",
        tmp_path / "storage-ac" / "persistent_state",
        tmp_path / "storage-fsac" / "persistent_state",
        tmp_path / "worker" / "build",
        tmp_path / "worker" / "cache",
        tmp_path / "bb",
    ]
    assert all(path.exists() for path in expected_paths)
