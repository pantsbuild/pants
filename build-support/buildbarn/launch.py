# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

from fetch import DEFAULT_MANIFEST_PATH, FetchError, ImageSpec, ensure_images_available, load_manifest

DEFAULT_INSTANCE_NAME = "fuse"
DEFAULT_GRPC_PORT = 8980
DEFAULT_READINESS_TIMEOUT_SECONDS = 30.0

RunCommand = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ContainerProcess:
    name: str
    image: str


@dataclass(frozen=True)
class CacheOnlyBuildbarn:
    address: str
    instance_name: str
    grpc_port: int
    container_name: str
    temp_dir: Path
    config_path: Path
    logs_path: Path


class BuildbarnLauncher(AbstractContextManager[CacheOnlyBuildbarn]):
    def __init__(
        self,
        *,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        docker_binary: str = "docker",
        temp_dir: Path | None = None,
        instance_name: str = DEFAULT_INSTANCE_NAME,
        run_command: RunCommand | None = None,
        readiness_timeout_seconds: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
    ) -> None:
        self.manifest_path = manifest_path
        self.docker_binary = docker_binary
        self.instance_name = instance_name
        self.temp_dir = temp_dir
        self.run_command = run_command or _run_command
        self.readiness_timeout_seconds = readiness_timeout_seconds
        self._container: ContainerProcess | None = None
        self._launched: CacheOnlyBuildbarn | None = None

    def __enter__(self) -> CacheOnlyBuildbarn:
        self._launched = self.launch_cache_only()
        return self._launched

    def __exit__(self, exc_type, exc, tb) -> None:
        self.teardown()

    def launch_cache_only(self) -> CacheOnlyBuildbarn:
        images = load_manifest(self.manifest_path)
        cache_image = _select_image(images, "bb-storage")
        ensure_images_available([cache_image], docker_binary=self.docker_binary, run_command=self.run_command)

        temp_dir = self.temp_dir or Path(tempfile.mkdtemp(prefix="pants-buildbarn-cache-"))
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "bb_storage.jsonnet"
        logs_path = temp_dir / "bb_storage.log"
        _write_cache_only_config(config_path, instance_name=self.instance_name)
        _prepare_storage_dirs(temp_dir)

        container_name = f"pants-buildbarn-cache-{uuid.uuid4().hex[:12]}"
        self._run_docker(
            [
                self.docker_binary,
                "run",
                "--detach",
                "--rm",
                "--name",
                container_name,
                "--publish",
                f"127.0.0.1::{DEFAULT_GRPC_PORT}",
                "--volume",
                f"{config_path}:/config/bb_storage.jsonnet:ro",
                "--volume",
                f"{temp_dir / 'storage-cas'}:/storage-cas",
                "--volume",
                f"{temp_dir / 'storage-ac'}:/storage-ac",
                cache_image.reference,
                "/config/bb_storage.jsonnet",
            ],
            check=True,
        )
        self._container = ContainerProcess(name=container_name, image=cache_image.reference)

        try:
            grpc_port = _discover_host_port(
                container_name,
                container_port=DEFAULT_GRPC_PORT,
                docker_binary=self.docker_binary,
                run_command=self.run_command,
            )
            _wait_for_tcp_readiness(
                port=grpc_port,
                timeout_seconds=self.readiness_timeout_seconds,
                docker_binary=self.docker_binary,
                container_name=container_name,
                run_command=self.run_command,
            )
        except Exception:
            _write_container_logs(
                logs_path,
                container_name=container_name,
                docker_binary=self.docker_binary,
                run_command=self.run_command,
            )
            self.teardown(remove_temp_dir=False)
            raise

        launched = CacheOnlyBuildbarn(
            address=f"grpc://127.0.0.1:{grpc_port}",
            instance_name=self.instance_name,
            grpc_port=grpc_port,
            container_name=container_name,
            temp_dir=temp_dir,
            config_path=config_path,
            logs_path=logs_path,
        )
        self._launched = launched
        return launched

    def teardown(self, *, remove_temp_dir: bool = True) -> None:
        if self._container is not None and self._launched is not None:
            _write_container_logs(
                self._launched.logs_path,
                container_name=self._container.name,
                docker_binary=self.docker_binary,
                run_command=self.run_command,
            )
        if self._container is not None:
            self._run_docker([self.docker_binary, "rm", "--force", self._container.name], check=False)
            self._container = None
        if remove_temp_dir and self.temp_dir is None and self._launched is not None:
            shutil.rmtree(self._launched.temp_dir, ignore_errors=True)
        self._launched = None

    def _run_docker(self, args: Sequence[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return self.run_command(args, check)


def _select_image(images: Sequence[ImageSpec], name: str) -> ImageSpec:
    for image in images:
        if image.name == name:
            return image
    raise FetchError(f"Buildbarn image manifest does not define the required image {name!r}")


def _prepare_storage_dirs(temp_dir: Path) -> None:
    for relative_path in [
        Path("storage-cas/persistent_state"),
        Path("storage-ac/persistent_state"),
    ]:
        (temp_dir / relative_path).mkdir(parents=True, exist_ok=True)


def _write_cache_only_config(config_path: Path, *, instance_name: str) -> None:
    config_path.write_text(
        f"""{{
  grpcServers: [{{
    listenAddresses: [':{DEFAULT_GRPC_PORT}'],
    authenticationPolicy: {{ allow: {{}} }},
  }}],
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {{
    backend: {{
      'local': {{
        keyLocationMapOnBlockDevice: {{
          file: {{
            path: '/storage-cas/key_location_map',
            sizeBytes: 16 * 1024 * 1024,
          }},
        }},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 3,
        blocksOnBlockDevice: {{
          source: {{
            file: {{
              path: '/storage-cas/blocks',
              sizeBytes: 1024 * 1024 * 1024,
            }},
          }},
          spareBlocks: 3,
        }},
        persistent: {{
          stateDirectoryPath: '/storage-cas/persistent_state',
          minimumEpochInterval: '300s',
        }},
      }},
    }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
    findMissingAuthorizer: {{ allow: {{}} }},
  }},
  actionCache: {{
    backend: {{
      'local': {{
        keyLocationMapOnBlockDevice: {{
          file: {{
            path: '/storage-ac/key_location_map',
            sizeBytes: 1024 * 1024,
          }},
        }},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 1,
        blocksOnBlockDevice: {{
          source: {{
            file: {{
              path: '/storage-ac/blocks',
              sizeBytes: 128 * 1024 * 1024,
            }},
          }},
          spareBlocks: 3,
        }},
        persistent: {{
          stateDirectoryPath: '/storage-ac/persistent_state',
          minimumEpochInterval: '300s',
        }},
      }},
    }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ instanceNamePrefix: {{
      allowedInstanceNamePrefixes: ['{instance_name}'],
    }} }},
  }},
}}
""",
        encoding="utf-8",
    )


def _discover_host_port(
    container_name: str,
    *,
    container_port: int,
    docker_binary: str,
    run_command: RunCommand,
) -> int:
    result = run_command([docker_binary, "port", container_name, f"{container_port}/tcp"], True)
    port_mapping = result.stdout.strip()
    _, _, host_port = port_mapping.rpartition(":")
    if not host_port.isdigit():
        raise FetchError(
            f"Docker did not return a valid host port mapping for {container_name}: {port_mapping!r}"
        )
    return int(host_port)


def _wait_for_tcp_readiness(
    *,
    port: int,
    timeout_seconds: float,
    docker_binary: str,
    container_name: str,
    run_command: RunCommand,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _container_exited(
            container_name,
            docker_binary=docker_binary,
            run_command=run_command,
        ):
            raise FetchError(f"Buildbarn container exited before becoming ready: {container_name}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.1)
    raise FetchError(f"Timed out waiting for Buildbarn gRPC port {port} to become ready")


def _container_exited(
    container_name: str,
    *,
    docker_binary: str,
    run_command: RunCommand,
) -> bool:
    result = run_command(
        [docker_binary, "inspect", "--format", "{{.State.Running}}", container_name],
        False,
    )
    return result.returncode != 0 or result.stdout.strip().lower() != "true"


def _write_container_logs(
    logs_path: Path,
    *,
    container_name: str,
    docker_binary: str,
    run_command: RunCommand,
) -> None:
    result = run_command([docker_binary, "logs", container_name], False)
    logs_path.write_text(result.stdout + result.stderr, encoding="utf-8")


def _run_command(args: Sequence[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch local Buildbarn services for Pants tests.")
    parser.add_argument("mode", choices=["cache-only"])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--docker-binary", default="docker")
    parser.add_argument("--instance-name", default=DEFAULT_INSTANCE_NAME)
    parser.add_argument("--temp-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(argv)
    if options.mode != "cache-only":
        raise FetchError(f"Unsupported Buildbarn mode: {options.mode}")

    with BuildbarnLauncher(
        manifest_path=options.manifest,
        docker_binary=options.docker_binary,
        temp_dir=options.temp_dir,
        instance_name=options.instance_name,
    ) as instance:
        print(instance.address)
        print(instance.config_path)
        print(instance.logs_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
