# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

DEFAULT_INSTANCE_NAME = "fuse"
DEFAULT_GRPC_PORT = 8980
DEFAULT_READINESS_TIMEOUT_SECONDS = 30.0

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ASSET_FILE_NAMES = (
    "cache.jsonnet",
    "docker-compose.cache.yaml",
    "docker-compose.remote-execution.yaml",
    "frontend.jsonnet",
    "runner.jsonnet",
    "scheduler.jsonnet",
    "storage.jsonnet",
    "worker.jsonnet",
    "images.json",
)

RunCommand = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]


class FetchError(ValueError):
    pass


@dataclass(frozen=True)
class ImageReference:
    repository: str
    tag: str
    digest: str


@dataclass(frozen=True)
class ImageSpec:
    name: str
    reference: str
    required_for: tuple[str, ...]

    @property
    def repository(self) -> str:
        return parse_image_reference(self.reference).repository


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


def parse_image_reference(reference: str) -> ImageReference:
    tagged_repository, separator, digest = reference.partition("@")
    tag_separator_index = tagged_repository.rfind(":")
    slash_index = tagged_repository.rfind("/")
    if tag_separator_index <= slash_index:
        raise FetchError(f"Image reference must include a tag before the digest: {reference}")

    if separator != "@" or not _DIGEST_RE.match(digest):
        raise FetchError(f"Image reference must be pinned by sha256 digest: {reference}")

    repository = tagged_repository[:tag_separator_index]
    tag = tagged_repository[tag_separator_index + 1 :]
    if not repository or not tag:
        raise FetchError(f"Image reference must include a repository and tag: {reference}")

    return ImageReference(repository=repository, tag=tag, digest=digest)


def load_manifest(manifest_path: Path | None = None) -> tuple[ImageSpec, ...]:
    if manifest_path is None:
        data = json.loads(files(__package__).joinpath("images.json").read_text(encoding="utf-8"))
    else:
        with manifest_path.open(encoding="utf-8") as fp:
            data = json.load(fp)

    if data.get("schema_version") != 1:
        raise FetchError(f"Unsupported Buildbarn image manifest schema version: {data.get('schema_version')!r}")

    images = data.get("images")
    if not isinstance(images, list) or not images:
        raise FetchError("Buildbarn image manifest must contain a non-empty images list")

    loaded: list[ImageSpec] = []
    seen_names: set[str] = set()
    for image_data in images:
        name = image_data.get("name")
        reference = image_data.get("reference")
        required_for = image_data.get("required_for")
        if not isinstance(name, str) or not name:
            raise FetchError(f"Every Buildbarn image must have a non-empty name: {image_data!r}")
        if name in seen_names:
            raise FetchError(f"Buildbarn image names must be unique, but {name!r} is duplicated")
        if not isinstance(reference, str):
            raise FetchError(f"Buildbarn image {name!r} must provide a string reference")
        if not isinstance(required_for, list) or not required_for or not all(
            isinstance(mode, str) and mode for mode in required_for
        ):
            raise FetchError(
                f"Buildbarn image {name!r} must provide a non-empty required_for list of strings"
            )

        parse_image_reference(reference)
        loaded.append(ImageSpec(name=name, reference=reference, required_for=tuple(required_for)))
        seen_names.add(name)

    return tuple(loaded)


def ensure_images_available(
    images: Iterable[ImageSpec],
    *,
    pull: bool = True,
    docker_binary: str = "docker",
    run_command: RunCommand | None = None,
) -> tuple[ImageSpec, ...]:
    runner = run_command or _run_command
    _ensure_compose_available(docker_binary=docker_binary, run_command=runner)

    pulled_images: list[ImageSpec] = []
    for image in images:
        if _image_exists(image.reference, docker_binary=docker_binary, run_command=runner):
            continue
        if not pull:
            raise FetchError(f"Docker image is not available locally: {image.reference}")
        runner([docker_binary, "pull", image.reference], True)
        pulled_images.append(image)
    return tuple(pulled_images)


class BuildbarnLauncher(AbstractContextManager[CacheOnlyBuildbarn]):
    def __init__(
        self,
        *,
        manifest_path: Path | None = None,
        docker_binary: str = "docker",
        temp_dir: Path | None = None,
        instance_name: str = DEFAULT_INSTANCE_NAME,
        run_command: RunCommand | None = None,
        readiness_timeout_seconds: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
    ) -> None:
        self.manifest_path = manifest_path
        self.docker_binary = docker_binary
        self.temp_dir = temp_dir
        self.instance_name = instance_name
        self.run_command = run_command or _run_command
        self.readiness_timeout_seconds = readiness_timeout_seconds
        self._project_name: str | None = None
        self._runtime_root: Path | None = None
        self._env_file: Path | None = None
        self._compose_file: Path | None = None
        self._active_services: tuple[str, ...] = ()
        self._launched: CacheOnlyBuildbarn | RemoteExecutionBuildbarn | None = None

    def __enter__(self) -> CacheOnlyBuildbarn:
        self._launched = self.launch_cache_only()
        return self._launched

    def __exit__(self, exc_type, exc, tb) -> None:
        self.teardown()

    def launch_cache_only(self) -> CacheOnlyBuildbarn:
        images = load_manifest(self.manifest_path)
        cache_image = _select_image(images, "bb-storage")
        ensure_images_available([cache_image], docker_binary=self.docker_binary, run_command=self.run_command)

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
                "BB_STORAGE_IMAGE": cache_image.reference,
            },
        )
        compose_file = assets_root / "docker-compose.cache.yaml"

        self._project_name = project_name
        self._runtime_root = runtime_root
        self._env_file = env_file
        self._compose_file = compose_file
        self._active_services = ("cache",)

        try:
            self._run_compose(["up", "-d", *self._active_services], check=True)
            grpc_port = _discover_compose_host_port(
                service="cache",
                container_port=DEFAULT_GRPC_PORT,
                timeout_seconds=self.readiness_timeout_seconds,
                launcher=self,
                required_services=self._active_services,
            )
            _wait_for_tcp_readiness(
                port=grpc_port,
                timeout_seconds=self.readiness_timeout_seconds,
                launcher=self,
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
        images = load_manifest(self.manifest_path)
        storage_image = _select_image(images, "bb-storage")
        scheduler_image = _select_image(images, "bb-scheduler")
        worker_image = _select_image(images, "bb-worker")
        runner_installer_image = _select_image(images, "bb-runner-installer")
        execution_image = _select_image(images, "ubuntu-act-22-04")
        ensure_images_available(
            [storage_image, scheduler_image, worker_image, runner_installer_image, execution_image],
            docker_binary=self.docker_binary,
            run_command=self.run_command,
        )

        runtime_root = self._prepare_runtime_root("pants-buildbarn-re-")
        _prepare_remote_execution_dirs(runtime_root)

        assets_root = runtime_root / "assets"
        _copy_assets(assets_root)
        _write_runtime_overlay(
            assets_root / "runtime.libsonnet",
            instance_name=self.instance_name,
            execution_image_reference=execution_image.reference,
        )

        project_name = f"pants-buildbarn-re-{uuid.uuid4().hex[:12]}"
        env_file = _write_compose_env_file(
            runtime_root / "compose.env",
            {
                "BUILDBARN_ASSETS_ROOT": str(assets_root),
                "BUILDBARN_RUNTIME_ROOT": str(runtime_root),
                "BB_STORAGE_IMAGE": storage_image.reference,
                "BB_SCHEDULER_IMAGE": scheduler_image.reference,
                "BB_WORKER_IMAGE": worker_image.reference,
                "BB_RUNNER_INSTALLER_IMAGE": runner_installer_image.reference,
                "BB_EXECUTION_IMAGE": execution_image.reference,
            },
        )
        compose_file = assets_root / "docker-compose.remote-execution.yaml"
        required_services = ("storage", "frontend", "scheduler", "runner", "worker")

        self._project_name = project_name
        self._runtime_root = runtime_root
        self._env_file = env_file
        self._compose_file = compose_file
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
                launcher=self,
                required_services=required_services,
            )
            _wait_for_tcp_readiness(
                port=grpc_port,
                timeout_seconds=self.readiness_timeout_seconds,
                launcher=self,
                required_services=required_services,
            )
            _wait_for_path(runtime_root / "worker" / "runner", timeout_seconds=self.readiness_timeout_seconds)
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
                f"container-image=docker://{execution_image.reference}",
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
            raise FetchError("Buildbarn Compose launcher was used before being configured")
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
                *args,
            ],
            check,
        )


def _select_image(images: Sequence[ImageSpec], name: str) -> ImageSpec:
    for image in images:
        if image.name == name:
            return image
    raise FetchError(f"Buildbarn image manifest does not define the required image {name!r}")


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
    resource_root = files(__package__)
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


def _discover_compose_host_port(
    *,
    service: str,
    container_port: int,
    timeout_seconds: float,
    launcher: BuildbarnLauncher,
    required_services: Sequence[str],
) -> int:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _raise_if_required_services_exited(launcher, required_services)
        result = launcher._run_compose(["port", service, f"{container_port}"], check=False)
        if result.returncode == 0:
            port_mapping = result.stdout.strip()
            _, _, host_port = port_mapping.rpartition(":")
            if host_port.isdigit():
                return int(host_port)
        time.sleep(0.1)
    raise FetchError(f"Timed out waiting for Compose to publish port {container_port} for {service}")


def _wait_for_tcp_readiness(
    *,
    port: int,
    timeout_seconds: float,
    launcher: BuildbarnLauncher,
    required_services: Sequence[str],
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _raise_if_required_services_exited(launcher, required_services)
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


def _raise_if_required_services_exited(launcher: BuildbarnLauncher, required_services: Sequence[str]) -> None:
    exited_services = set(_compose_services(launcher, status="exited"))
    failed_services = sorted(service for service in required_services if service in exited_services)
    if failed_services:
        raise FetchError(
            "Buildbarn Compose services exited before becoming ready: " + ", ".join(failed_services)
        )


def _compose_services(launcher: BuildbarnLauncher, *, status: str) -> tuple[str, ...]:
    result = launcher._run_compose(["ps", "--status", status, "--services"], check=False)
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _write_compose_logs(launcher: BuildbarnLauncher) -> None:
    if launcher._runtime_root is None:
        return
    logs_path = launcher._runtime_root / "logs" / "compose.log"
    result = launcher._run_compose(["logs", "--no-color", "--timestamps"], check=False)
    logs_path.write_text(result.stdout + result.stderr, encoding="utf-8")


def _ensure_compose_available(*, docker_binary: str, run_command: RunCommand) -> None:
    try:
        run_command([docker_binary, "version", "--format", "{{.Server.Version}}"], True)
        run_command([docker_binary, "compose", "version"], True)
    except FileNotFoundError as error:
        raise FetchError("Docker with the Compose plugin is required for Buildbarn integration tests") from error
    except subprocess.CalledProcessError as error:
        raise FetchError(
            "Docker with the Compose plugin is required for Buildbarn integration tests, but a "
            f"readiness check failed: {error.stderr.strip() or error.stdout.strip() or error}"
        ) from error


def _image_exists(reference: str, *, docker_binary: str, run_command: RunCommand) -> bool:
    result = run_command([docker_binary, "image", "inspect", reference], False)
    return result.returncode == 0


def _run_command(args: Sequence[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _default_runtime_parent_dir() -> str:
    override = os.environ.get("PANTS_BUILDBARN_RUNTIME_PARENT")
    parent = Path(override) if override else Path.cwd() / ".pants.d" / "buildbarn"
    parent.mkdir(parents=True, exist_ok=True)
    return str(parent)
