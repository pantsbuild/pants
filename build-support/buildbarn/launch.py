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
DEFAULT_STORAGE_GRPC_PORT = 8981
DEFAULT_SCHEDULER_CLIENT_GRPC_PORT = 8982
DEFAULT_SCHEDULER_WORKER_GRPC_PORT = 8983
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


@dataclass(frozen=True)
class RemoteExecutionBuildbarn:
    address: str
    instance_name: str
    grpc_port: int
    temp_dir: Path
    config_dir: Path
    logs_dir: Path
    network_name: str
    platform_properties: tuple[str, ...]
    frontend_container_name: str
    storage_container_name: str
    scheduler_container_name: str
    worker_container_name: str
    runner_container_name: str


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
        self._containers: list[ContainerProcess] = []
        self._container_logs: dict[str, Path] = {}
        self._network_name: str | None = None
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

        temp_dir = self.temp_dir or Path(tempfile.mkdtemp(prefix="pants-buildbarn-cache-"))
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "bb_storage.jsonnet"
        logs_path = temp_dir / "bb_storage.log"
        _write_cache_only_config(config_path, instance_name=self.instance_name)
        _prepare_storage_dirs(temp_dir)

        container_name = f"pants-buildbarn-cache-{uuid.uuid4().hex[:12]}"
        self._start_detached_container(
            name=container_name,
            image=cache_image.reference,
            logs_path=logs_path,
            args=[
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
        )

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

        temp_dir = self.temp_dir or Path(tempfile.mkdtemp(prefix="pants-buildbarn-re-"))
        temp_dir.mkdir(parents=True, exist_ok=True)
        _prepare_remote_execution_dirs(temp_dir)

        config_dir = temp_dir / "config"
        logs_dir = temp_dir / "logs"
        config_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        storage_config_path = config_dir / "storage.jsonnet"
        frontend_config_path = config_dir / "frontend.jsonnet"
        scheduler_config_path = config_dir / "scheduler.jsonnet"
        worker_config_path = config_dir / "worker.jsonnet"
        runner_config_path = config_dir / "runner.jsonnet"
        runner_socket_path = temp_dir / "worker" / "runner"

        _write_remote_execution_storage_config(storage_config_path)
        _write_remote_execution_frontend_config(frontend_config_path)
        _write_remote_execution_scheduler_config(scheduler_config_path)
        _write_remote_execution_worker_config(
            worker_config_path,
            instance_name=self.instance_name,
            execution_image_reference=execution_image.reference,
        )
        _write_remote_execution_runner_config(runner_config_path)

        network_name = f"pants-buildbarn-net-{uuid.uuid4().hex[:12]}"
        self._run_docker([self.docker_binary, "network", "create", network_name], check=True)
        self._network_name = network_name

        storage_container_name = f"pants-buildbarn-storage-{uuid.uuid4().hex[:12]}"
        scheduler_container_name = f"pants-buildbarn-scheduler-{uuid.uuid4().hex[:12]}"
        worker_container_name = f"pants-buildbarn-worker-{uuid.uuid4().hex[:12]}"
        runner_container_name = f"pants-buildbarn-runner-{uuid.uuid4().hex[:12]}"
        frontend_container_name = f"pants-buildbarn-frontend-{uuid.uuid4().hex[:12]}"

        try:
            self._start_detached_container(
                name=storage_container_name,
                image=storage_image.reference,
                logs_path=logs_dir / "storage.log",
                args=[
                    self.docker_binary,
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    storage_container_name,
                    "--network",
                    network_name,
                    "--network-alias",
                    "storage",
                    "--volume",
                    f"{config_dir}:/config:ro",
                    "--volume",
                    f"{temp_dir / 'storage-cas'}:/storage-cas",
                    "--volume",
                    f"{temp_dir / 'storage-ac'}:/storage-ac",
                    "--volume",
                    f"{temp_dir / 'storage-fsac'}:/storage-fsac",
                    storage_image.reference,
                    "/config/storage.jsonnet",
                ],
            )
            self._start_detached_container(
                name=scheduler_container_name,
                image=scheduler_image.reference,
                logs_path=logs_dir / "scheduler.log",
                args=[
                    self.docker_binary,
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    scheduler_container_name,
                    "--network",
                    network_name,
                    "--network-alias",
                    "scheduler",
                    "--volume",
                    f"{config_dir}:/config:ro",
                    scheduler_image.reference,
                    "/config/scheduler.jsonnet",
                ],
            )

            installer_logs_path = logs_dir / "runner-installer.log"
            installer_result = self._run_docker(
                [
                    self.docker_binary,
                    "run",
                    "--rm",
                    "--volume",
                    f"{temp_dir / 'bb'}:/bb",
                    runner_installer_image.reference,
                ],
                check=True,
            )
            installer_logs_path.write_text(installer_result.stdout + installer_result.stderr, encoding="utf-8")

            self._start_detached_container(
                name=runner_container_name,
                image=execution_image.reference,
                logs_path=logs_dir / "runner.log",
                args=[
                    self.docker_binary,
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    runner_container_name,
                    "--network",
                    "none",
                    "--volume",
                    f"{config_dir}:/config:ro",
                    "--volume",
                    f"{temp_dir / 'bb'}:/bb",
                    "--volume",
                    f"{temp_dir / 'worker'}:/worker",
                    execution_image.reference,
                    "sh",
                    "-c",
                    "while ! test -f /bb/installed; do sleep 1; done; exec /bb/bb_runner /config/runner.jsonnet",
                ],
            )
            self._start_detached_container(
                name=worker_container_name,
                image=worker_image.reference,
                logs_path=logs_dir / "worker.log",
                args=[
                    self.docker_binary,
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    worker_container_name,
                    "--network",
                    network_name,
                    "--network-alias",
                    "worker",
                    "--volume",
                    f"{config_dir}:/config:ro",
                    "--volume",
                    f"{temp_dir / 'worker'}:/worker",
                    worker_image.reference,
                    "/config/worker.jsonnet",
                ],
            )
            self._start_detached_container(
                name=frontend_container_name,
                image=storage_image.reference,
                logs_path=logs_dir / "frontend.log",
                args=[
                    self.docker_binary,
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    frontend_container_name,
                    "--network",
                    network_name,
                    "--publish",
                    f"127.0.0.1::{DEFAULT_GRPC_PORT}",
                    "--volume",
                    f"{config_dir}:/config:ro",
                    storage_image.reference,
                    "/config/frontend.jsonnet",
                ],
            )

            grpc_port = _discover_host_port(
                frontend_container_name,
                container_port=DEFAULT_GRPC_PORT,
                docker_binary=self.docker_binary,
                run_command=self.run_command,
            )
            _wait_for_tcp_readiness(
                port=grpc_port,
                timeout_seconds=self.readiness_timeout_seconds,
                docker_binary=self.docker_binary,
                container_name=frontend_container_name,
                run_command=self.run_command,
            )
            _wait_for_path(runner_socket_path, timeout_seconds=self.readiness_timeout_seconds)
        except Exception:
            self.teardown(remove_temp_dir=False)
            raise

        launched = RemoteExecutionBuildbarn(
            address=f"grpc://127.0.0.1:{grpc_port}",
            instance_name=self.instance_name,
            grpc_port=grpc_port,
            temp_dir=temp_dir,
            config_dir=config_dir,
            logs_dir=logs_dir,
            network_name=network_name,
            platform_properties=(
                "OSFamily=linux",
                f"container-image=docker://{execution_image.reference}",
            ),
            frontend_container_name=frontend_container_name,
            storage_container_name=storage_container_name,
            scheduler_container_name=scheduler_container_name,
            worker_container_name=worker_container_name,
            runner_container_name=runner_container_name,
        )
        self._launched = launched
        return launched

    def teardown(self, *, remove_temp_dir: bool = True) -> None:
        for container in self._containers:
            logs_path = self._container_logs.get(container.name)
            if logs_path is not None:
                _write_container_logs(
                    logs_path,
                    container_name=container.name,
                    docker_binary=self.docker_binary,
                    run_command=self.run_command,
                )
        for container in reversed(self._containers):
            self._run_docker([self.docker_binary, "rm", "--force", container.name], check=False)
        self._containers.clear()
        self._container_logs.clear()
        if self._network_name is not None:
            self._run_docker([self.docker_binary, "network", "rm", self._network_name], check=False)
            self._network_name = None
        if remove_temp_dir and self.temp_dir is None and self._launched is not None:
            shutil.rmtree(self._launched.temp_dir, ignore_errors=True)
        self._launched = None

    def _run_docker(self, args: Sequence[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return self.run_command(args, check)

    def _start_detached_container(
        self,
        *,
        name: str,
        image: str,
        logs_path: Path,
        args: Sequence[str],
    ) -> None:
        self._run_docker(args, check=True)
        self._containers.append(ContainerProcess(name=name, image=image))
        self._container_logs[name] = logs_path


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


def _prepare_remote_execution_dirs(temp_dir: Path) -> None:
    for relative_path in [
        Path("storage-cas/persistent_state"),
        Path("storage-ac/persistent_state"),
        Path("storage-fsac/persistent_state"),
        Path("worker/build"),
        Path("worker/cache"),
        Path("bb"),
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


def _write_remote_execution_storage_config(config_path: Path) -> None:
    config_path.write_text(
        f"""{{
  grpcServers: [{{
    listenAddresses: [':{DEFAULT_STORAGE_GRPC_PORT}'],
    authenticationPolicy: {{ allow: {{}} }},
  }}],
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {{
    backend: {{
      'local': {{
        keyLocationMapOnBlockDevice: {{ file: {{ path: '/storage-cas/key_location_map', sizeBytes: 16 * 1024 * 1024 }} }},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 3,
        blocksOnBlockDevice: {{ source: {{ file: {{ path: '/storage-cas/blocks', sizeBytes: 1024 * 1024 * 1024 }} }}, spareBlocks: 3 }},
        persistent: {{ stateDirectoryPath: '/storage-cas/persistent_state', minimumEpochInterval: '300s' }},
      }},
    }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
    findMissingAuthorizer: {{ allow: {{}} }},
  }},
  actionCache: {{
    backend: {{
      'local': {{
        keyLocationMapOnBlockDevice: {{ file: {{ path: '/storage-ac/key_location_map', sizeBytes: 1024 * 1024 }} }},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 1,
        blocksOnBlockDevice: {{ source: {{ file: {{ path: '/storage-ac/blocks', sizeBytes: 128 * 1024 * 1024 }} }}, spareBlocks: 3 }},
        persistent: {{ stateDirectoryPath: '/storage-ac/persistent_state', minimumEpochInterval: '300s' }},
      }},
    }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
  }},
  fileSystemAccessCache: {{
    backend: {{
      'local': {{
        keyLocationMapOnBlockDevice: {{ file: {{ path: '/storage-fsac/key_location_map', sizeBytes: 1024 * 1024 }} }},
        keyLocationMapMaximumGetAttempts: 16,
        keyLocationMapMaximumPutAttempts: 64,
        oldBlocks: 8,
        currentBlocks: 24,
        newBlocks: 1,
        blocksOnBlockDevice: {{ source: {{ file: {{ path: '/storage-fsac/blocks', sizeBytes: 128 * 1024 * 1024 }} }}, spareBlocks: 3 }},
        persistent: {{ stateDirectoryPath: '/storage-fsac/persistent_state', minimumEpochInterval: '300s' }},
      }},
    }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
  }},
}}
""",
        encoding="utf-8",
    )


def _write_remote_execution_frontend_config(config_path: Path) -> None:
    config_path.write_text(
        f"""{{
  grpcServers: [{{
    listenAddresses: [':{DEFAULT_GRPC_PORT}'],
    authenticationPolicy: {{ allow: {{}} }},
  }}],
  schedulers: {{
    '': {{
      endpoint: {{
        address: 'scheduler:{DEFAULT_SCHEDULER_CLIENT_GRPC_PORT}',
        addMetadataJmespathExpression: {{
          expression: |||
            {{
              "build.bazel.remote.execution.v2.requestmetadata-bin": incomingGRPCMetadata."build.bazel.remote.execution.v2.requestmetadata-bin"
            }}
          |||,
        }},
      }},
    }},
  }},
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {{
    backend: {{ grpc: {{ client: {{ address: 'storage:{DEFAULT_STORAGE_GRPC_PORT}' }} }} }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
    findMissingAuthorizer: {{ allow: {{}} }},
  }},
  actionCache: {{
    backend: {{
      completenessChecking: {{
        backend: {{ grpc: {{ client: {{ address: 'storage:{DEFAULT_STORAGE_GRPC_PORT}' }} }} }},
        maximumTotalTreeSizeBytes: 64 * 1024 * 1024,
      }},
    }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
  }},
  fileSystemAccessCache: {{
    backend: {{ grpc: {{ client: {{ address: 'storage:{DEFAULT_STORAGE_GRPC_PORT}' }} }} }},
    getAuthorizer: {{ allow: {{}} }},
    putAuthorizer: {{ allow: {{}} }},
  }},
  executeAuthorizer: {{ allow: {{}} }},
}}
""",
        encoding="utf-8",
    )


def _write_remote_execution_scheduler_config(config_path: Path) -> None:
    config_path.write_text(
        f"""{{
  clientGrpcServers: [{{
    listenAddresses: [':{DEFAULT_SCHEDULER_CLIENT_GRPC_PORT}'],
    authenticationPolicy: {{ allow: {{}} }},
  }}],
  workerGrpcServers: [{{
    listenAddresses: [':{DEFAULT_SCHEDULER_WORKER_GRPC_PORT}'],
    authenticationPolicy: {{ allow: {{}} }},
  }}],
  buildQueueStateGrpcServers: [{{
    listenAddresses: [':8984'],
    authenticationPolicy: {{ allow: {{}} }},
  }}],
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  contentAddressableStorage: {{ grpc: {{ client: {{ address: 'storage:{DEFAULT_STORAGE_GRPC_PORT}' }} }} }},
  executeAuthorizer: {{ allow: {{}} }},
  modifyDrainsAuthorizer: {{ allow: {{}} }},
  killOperationsAuthorizer: {{ allow: {{}} }},
  synchronizeAuthorizer: {{ allow: {{}} }},
  actionRouter: {{
    simple: {{
      platformKeyExtractor: {{ action: {{}} }},
      invocationKeyExtractors: [{{ correlatedInvocationsId: {{}} }}, {{ toolInvocationId: {{}} }}],
      initialSizeClassAnalyzer: {{
        defaultExecutionTimeout: '1800s',
        maximumExecutionTimeout: '7200s',
      }},
    }},
  }},
  platformQueueWithNoWorkersTimeout: '900s',
}}
""",
        encoding="utf-8",
    )


def _write_remote_execution_worker_config(
    config_path: Path,
    *,
    instance_name: str,
    execution_image_reference: str,
) -> None:
    config_path.write_text(
        f"""{{
  blobstore: {{
    contentAddressableStorage: {{ grpc: {{ client: {{ address: 'storage:{DEFAULT_STORAGE_GRPC_PORT}' }} }} }},
    actionCache: {{
      completenessChecking: {{
        backend: {{ grpc: {{ client: {{ address: 'storage:{DEFAULT_STORAGE_GRPC_PORT}' }} }} }},
        maximumTotalTreeSizeBytes: 64 * 1024 * 1024,
      }},
    }},
  }},
  maximumMessageSizeBytes: 16 * 1024 * 1024,
  scheduler: {{ address: 'scheduler:{DEFAULT_SCHEDULER_WORKER_GRPC_PORT}' }},
  buildDirectories: [{{
    native: {{
      buildDirectoryPath: '/worker/build',
      cacheDirectoryPath: '/worker/cache',
      maximumCacheFileCount: 1000,
      maximumCacheSizeBytes: 512 * 1024 * 1024,
      cacheReplacementPolicy: 'LEAST_RECENTLY_USED',
    }},
    runners: [{{
      endpoint: {{ address: 'unix:///worker/runner' }},
      concurrency: 1,
      instanceNamePrefix: '{instance_name}',
      platform: {{
        properties: [
          {{ name: 'OSFamily', value: 'linux' }},
          {{ name: 'container-image', value: 'docker://{execution_image_reference}' }},
        ],
      }},
      workerId: {{
        datacenter: 'pants',
        rack: 'buildbarn',
        slot: '1',
        hostname: 'pants-buildbarn-worker',
      }},
    }}],
  }}],
  inputDownloadConcurrency: 4,
  outputUploadConcurrency: 4,
  directoryCache: {{
    maximumCount: 1000,
    maximumSizeBytes: 1000 * 1024,
    cacheReplacementPolicy: 'LEAST_RECENTLY_USED',
  }},
}}
""",
        encoding="utf-8",
    )


def _write_remote_execution_runner_config(config_path: Path) -> None:
    config_path.write_text(
        """{
  buildDirectoryPath: '/worker/build',
  grpcServers: [{
    listenPaths: ['/worker/runner'],
    authenticationPolicy: { allow: {} },
  }],
}
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


def _wait_for_path(path: Path, *, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.1)
    raise FetchError(f"Timed out waiting for Buildbarn path to appear: {path}")


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
    parser.add_argument("mode", choices=["cache-only", "remote-execution"])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--docker-binary", default="docker")
    parser.add_argument("--instance-name", default=DEFAULT_INSTANCE_NAME)
    parser.add_argument("--temp-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(argv)
    launcher = BuildbarnLauncher(
        manifest_path=options.manifest,
        docker_binary=options.docker_binary,
        temp_dir=options.temp_dir,
        instance_name=options.instance_name,
    )
    if options.mode == "cache-only":
        with launcher as instance:
            print(instance.address)
            print(instance.config_path)
            print(instance.logs_path)
        return 0

    if options.mode == "remote-execution":
        try:
            instance = launcher.launch_remote_execution()
            print(instance.address)
            print(instance.config_dir)
            print(instance.logs_dir)
            print("\n".join(instance.platform_properties))
        finally:
            launcher.teardown()
        return 0

    raise FetchError(f"Unsupported Buildbarn mode: {options.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
