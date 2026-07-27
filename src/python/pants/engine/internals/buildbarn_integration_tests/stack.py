# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

DEFAULT_INSTANCE_NAME = "fuse"
DEFAULT_GRPC_PORT = 8980
DEFAULT_READINESS_TIMEOUT_SECONDS = 30.0

_CONFIG_ROOT = files(__package__).joinpath("config")
_COMPOSE_FILE_NAME = "docker-compose.yaml"
_IMAGE_CONFIG_FILE_NAME = "docker-compose.images.yaml"
_ASSET_FILE_NAMES = (
    "cache.jsonnet",
    _COMPOSE_FILE_NAME,
    _IMAGE_CONFIG_FILE_NAME,
    "frontend.jsonnet",
    "runner.jsonnet",
    "scheduler.jsonnet",
    "storage.jsonnet",
    "worker.jsonnet",
)
_EXECUTION_IMAGE_SERVICE = "execution-image"

RunCommand = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]


class FetchError(ValueError):
    pass


@dataclass(frozen=True)
class CacheOnlyBuildbarn:
    address: str
    instance_name: str
    grpc_port: int
    project_name: str
    temp_dir: Path
    logs_path: Path


@dataclass(frozen=True)
class RemoteExecutionBuildbarn:
    address: str
    instance_name: str
    grpc_port: int
    project_name: str
    temp_dir: Path
    logs_dir: Path
    platform_properties: tuple[str, ...]


class LocalBuildbarnStack(AbstractContextManager[CacheOnlyBuildbarn]):
    def __init__(
        self,
        *,
        docker_binary: str = "docker",
        temp_dir: Path | None = None,
        instance_name: str = DEFAULT_INSTANCE_NAME,
        run_command: RunCommand | None = None,
        readiness_timeout_seconds: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
    ) -> None:
        self.docker_binary = docker_binary
        self.temp_dir = temp_dir
        self.instance_name = instance_name
        self.run_command = run_command or _run_command
        self.readiness_timeout_seconds = readiness_timeout_seconds
        self._project_name: str | None = None
        self._runtime_root: Path | None = None
        self._env_file: Path | None = None
        self._compose_file: Path | None = None
        self._compose_profiles: tuple[str, ...] = ()
        self._active_services: tuple[str, ...] = ()
        self._launched: CacheOnlyBuildbarn | RemoteExecutionBuildbarn | None = None

    def __enter__(self) -> CacheOnlyBuildbarn:
        self._launched = self.launch_cache_only()
        return self._launched

    def __exit__(self, exc_type, exc, tb) -> None:
        self.teardown()

    def launch_cache_only(self) -> CacheOnlyBuildbarn:
        runtime_root = self._prepare_runtime_root("pants-buildbarn-cache-")
        _prepare_storage_dirs(runtime_root)

        assets_root = runtime_root / "assets"
        _copy_assets(assets_root)
        _write_runtime_overlay(
            assets_root / "runtime.libsonnet",
            instance_name=self.instance_name,
            execution_image_reference="",
        )

        project_name = f"pants-buildbarn-cache-{uuid.uuid4().hex[:12]}"
        env_file = _write_compose_env_file(
            runtime_root / "compose.env",
            {
                "BUILDBARN_ASSETS_ROOT": str(assets_root),
                "BUILDBARN_RUNTIME_ROOT": str(runtime_root),
            },
        )
        compose_file = assets_root / _COMPOSE_FILE_NAME

        self._project_name = project_name
        self._runtime_root = runtime_root
        self._env_file = env_file
        self._compose_file = compose_file
        self._compose_profiles = ("cache",)
        self._active_services = ("cache",)

        try:
            self._run_compose(["up", "-d", *self._active_services], check=True)
            grpc_port = _discover_compose_host_port(
                service="cache",
                container_port=DEFAULT_GRPC_PORT,
                timeout_seconds=self.readiness_timeout_seconds,
                stack=self,
                required_services=self._active_services,
            )
            _wait_for_tcp_readiness(
                port=grpc_port,
                timeout_seconds=self.readiness_timeout_seconds,
                stack=self,
                required_services=self._active_services,
            )
        except Exception:
            self.teardown(remove_temp_dir=False)
            raise

        launched = CacheOnlyBuildbarn(
            address=f"grpc://127.0.0.1:{grpc_port}",
            instance_name=self.instance_name,
            grpc_port=grpc_port,
            project_name=project_name,
            temp_dir=runtime_root,
            logs_path=runtime_root / "logs" / "compose.log",
        )
        self._launched = launched
        return launched

    def launch_remote_execution(self) -> RemoteExecutionBuildbarn:
        runtime_root = self._prepare_runtime_root("pants-buildbarn-re-")
        _prepare_remote_execution_dirs(runtime_root)

        assets_root = runtime_root / "assets"
        _copy_assets(assets_root)
        execution_image = _load_configured_service_image(
            assets_root / _IMAGE_CONFIG_FILE_NAME, _EXECUTION_IMAGE_SERVICE
        )
        _write_runtime_overlay(
            assets_root / "runtime.libsonnet",
            instance_name=self.instance_name,
            execution_image_reference=execution_image,
        )

        project_name = f"pants-buildbarn-re-{uuid.uuid4().hex[:12]}"
        env_file = _write_compose_env_file(
            runtime_root / "compose.env",
            {
                "BUILDBARN_ASSETS_ROOT": str(assets_root),
                "BUILDBARN_RUNTIME_ROOT": str(runtime_root),
            },
        )
        compose_file = assets_root / _COMPOSE_FILE_NAME
        required_services = ("storage", "frontend", "scheduler", "runner", "worker")

        self._project_name = project_name
        self._runtime_root = runtime_root
        self._env_file = env_file
        self._compose_file = compose_file
        self._compose_profiles = ("remote_execution",)
        self._active_services = (
            "storage",
            "frontend",
            "scheduler",
            "runner-installer",
            "runner",
            "worker",
        )

        try:
            self._run_compose(["up", "-d", *self._active_services], check=True)
            grpc_port = _discover_compose_host_port(
                service="frontend",
                container_port=DEFAULT_GRPC_PORT,
                timeout_seconds=self.readiness_timeout_seconds,
                stack=self,
                required_services=required_services,
            )
            _wait_for_tcp_readiness(
                port=grpc_port,
                timeout_seconds=self.readiness_timeout_seconds,
                stack=self,
                required_services=required_services,
            )
            _wait_for_path(
                runtime_root / "worker" / "runner", timeout_seconds=self.readiness_timeout_seconds
            )
        except Exception:
            self.teardown(remove_temp_dir=False)
            raise

        launched = RemoteExecutionBuildbarn(
            address=f"grpc://127.0.0.1:{grpc_port}",
            instance_name=self.instance_name,
            grpc_port=grpc_port,
            project_name=project_name,
            temp_dir=runtime_root,
            logs_dir=runtime_root / "logs",
            platform_properties=(
                "OSFamily=linux",
                f"container-image=docker://{execution_image}",
            ),
        )
        self._launched = launched
        return launched

    def teardown(self, *, remove_temp_dir: bool = True) -> None:
        if self._project_name is not None and self._runtime_root is not None:
            _write_compose_logs(self)
            self._run_compose(["down", "-v", "--remove-orphans"], check=False)

        if remove_temp_dir and self.temp_dir is None and self._runtime_root is not None:
            shutil.rmtree(self._runtime_root, ignore_errors=True)

        self._project_name = None
        self._runtime_root = None
        self._env_file = None
        self._compose_file = None
        self._compose_profiles = ()
        self._active_services = ()
        self._launched = None

    def _prepare_runtime_root(self, prefix: str) -> Path:
        runtime_root = self.temp_dir or Path(
            tempfile.mkdtemp(prefix=prefix, dir=_default_runtime_parent_dir())
        )
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
        return runtime_root

    def _run_compose(self, args: Sequence[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        if self._project_name is None or self._env_file is None or self._compose_file is None:
            raise FetchError("Buildbarn Compose stack was used before being configured")
        profile_args = tuple(
            arg for profile in self._compose_profiles for arg in ("--profile", profile)
        )
        return self.run_command(
            [
                self.docker_binary,
                "compose",
                "--project-name",
                self._project_name,
                "--file",
                str(self._compose_file),
                "--env-file",
                str(self._env_file),
                *profile_args,
                *args,
            ],
            check,
        )


def _prepare_storage_dirs(runtime_root: Path) -> None:
    for relative_path in [
        Path("storage-cas/persistent_state"),
        Path("storage-ac/persistent_state"),
    ]:
        (runtime_root / relative_path).mkdir(parents=True, exist_ok=True)


def _prepare_remote_execution_dirs(runtime_root: Path) -> None:
    for relative_path in [
        Path("storage-cas/persistent_state"),
        Path("storage-ac/persistent_state"),
        Path("storage-fsac/persistent_state"),
        Path("worker/build"),
        Path("worker/cache"),
        Path("bb"),
    ]:
        (runtime_root / relative_path).mkdir(parents=True, exist_ok=True)


def _copy_assets(destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    resource_root = _CONFIG_ROOT
    for name in _ASSET_FILE_NAMES:
        destination_dir.joinpath(name).write_text(
            resource_root.joinpath(name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _write_runtime_overlay(
    path: Path,
    *,
    instance_name: str,
    execution_image_reference: str,
) -> None:
    path.write_text(
        "{\n"
        f"  instanceName: {json.dumps(instance_name)},\n"
        f"  executionImage: {json.dumps(execution_image_reference)},\n"
        "}\n",
        encoding="utf-8",
    )


def _write_compose_env_file(path: Path, values: dict[str, str]) -> Path:
    path.write_text(
        "\n".join(f"{name}={value}" for name, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return path


def _load_configured_service_image(config_path: Path, service: str) -> str:
    in_services = False
    in_service = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_services = stripped == "services:"
            in_service = False
            continue
        if not in_services:
            continue
        if indent == 2:
            in_service = stripped == f"{service}:"
            continue
        if in_service and indent == 4 and stripped.startswith("image:"):
            image = stripped.removeprefix("image:").strip().strip("'\"")
            if image:
                return image

    raise FetchError(f"Buildbarn Compose image config does not define image for {service!r}")


def _discover_compose_host_port(
    *,
    service: str,
    container_port: int,
    timeout_seconds: float,
    stack: LocalBuildbarnStack,
    required_services: Sequence[str],
) -> int:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _raise_if_required_services_exited(stack, required_services)
        result = stack._run_compose(["port", service, f"{container_port}"], check=False)
        if result.returncode == 0:
            port_mapping = result.stdout.strip()
            _, _, host_port = port_mapping.rpartition(":")
            if host_port.isdigit():
                return int(host_port)
        time.sleep(0.1)
    raise FetchError(
        f"Timed out waiting for Compose to publish port {container_port} for {service}"
    )


def _wait_for_tcp_readiness(
    *,
    port: int,
    timeout_seconds: float,
    stack: LocalBuildbarnStack,
    required_services: Sequence[str],
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _raise_if_required_services_exited(stack, required_services)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.1)
    raise FetchError(f"Timed out waiting for Buildbarn gRPC port {port} to become ready")


def _wait_for_path(path: Path, *, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.1)
    raise FetchError(f"Timed out waiting for Buildbarn path to appear: {path}")


def _raise_if_required_services_exited(
    stack: LocalBuildbarnStack, required_services: Sequence[str]
) -> None:
    exited_services = set(_compose_services(stack, status="exited"))
    failed_services = sorted(service for service in required_services if service in exited_services)
    if failed_services:
        raise FetchError(
            "Buildbarn Compose services exited before becoming ready: " + ", ".join(failed_services)
        )


def _compose_services(stack: LocalBuildbarnStack, *, status: str) -> tuple[str, ...]:
    result = stack._run_compose(["ps", "--status", status, "--services"], check=False)
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _write_compose_logs(stack: LocalBuildbarnStack) -> None:
    if stack._runtime_root is None:
        return
    logs_path = stack._runtime_root / "logs" / "compose.log"
    result = stack._run_compose(["logs", "--no-color", "--timestamps"], check=False)
    logs_path.write_text(result.stdout + result.stderr, encoding="utf-8")


def _run_command(args: Sequence[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _default_runtime_parent_dir() -> str:
    override = os.environ.get("PANTS_BUILDBARN_RUNTIME_PARENT")
    parent = Path(override) if override else Path.cwd() / ".pants.d" / "buildbarn"
    parent.mkdir(parents=True, exist_ok=True)
    return str(parent)
