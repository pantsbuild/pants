# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple, cast

from typing_extensions import Protocol

from pants.base.exiter import ExitCode
from pants.engine.fs import PathGlobs
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import (
    PyExecutionStrategyOptions,
    PyExecutor,
    PyNailgunClient,
    PyNailgunServer,
    PyRemotingOptions,
    PyScheduler,
    PySessionCancellationLatch,
    PyTypes,
)
from pants.option.global_options import ExecutionOptions
from pants.util.memo import memoized_property
from pants.util.meta import SingletonMetaclass


class RawFdRunner(Protocol):
    def __call__(
        self,
        command: str,
        args: Tuple[str, ...],
        env: Dict[str, str],
        working_directory: bytes,
        cancellation_latch: PySessionCancellationLatch,
        stdin_fd: int,
        stdout_fd: int,
        stderr_fd: int,
    ) -> ExitCode:
        ...


class Native(metaclass=SingletonMetaclass):
    """Encapsulates fetching a platform specific version of the native portion of the engine."""

    @memoized_property
    def lib(self):
        """Load the native engine as a python module."""
        return native_engine

    def set_per_run_log_path(self, path: Optional[str]) -> None:
        """Instructs the logging code to also write emitted logs to a run-specific log file; or
        disables writing to any run-specific file if `None` is passed."""
        self.lib.set_per_run_log_path(path)

    def match_path_globs(self, path_globs: PathGlobs, paths: Iterable[str]) -> Tuple[str, ...]:
        """Return all paths that match the PathGlobs."""
        return tuple(self.lib.match_path_globs(path_globs, tuple(paths)))

    def nailgun_server_await_shutdown(self, nailgun_server) -> None:
        """Blocks until the server has shut down.

        Raises an exception if the server exited abnormally
        """
        self.lib.nailgun_server_await_shutdown(nailgun_server)

    def new_nailgun_server(
        self, executor: PyExecutor, port: int, runner: RawFdRunner
    ) -> PyNailgunServer:
        """Creates a nailgun server with a requested port.

        Returns the server and the actual port it bound to.
        """
        return cast(PyNailgunServer, self.lib.nailgun_server_create(executor, port, runner))

    def new_nailgun_client(self, executor: PyExecutor, port: int) -> PyNailgunClient:
        return cast(PyNailgunClient, self.lib.nailgun_client_create(executor, port))

    def new_scheduler(
        self,
        tasks,
        build_root: str,
        local_store_dir: str,
        local_execution_root_dir: str,
        named_caches_dir: str,
        ca_certs_path: Optional[str],
        ignore_patterns: List[str],
        use_gitignore: bool,
        executor: PyExecutor,
        execution_options: ExecutionOptions,
        types: PyTypes,
    ) -> PyScheduler:
        """Create and return a native Scheduler."""

        remoting_options = PyRemotingOptions(
            execution_enable=execution_options.remote_execution,
            store_address=execution_options.remote_store_address,
            execution_address=execution_options.remote_execution_address,
            execution_process_cache_namespace=execution_options.process_execution_cache_namespace,
            instance_name=execution_options.remote_instance_name,
            root_ca_certs_path=execution_options.remote_ca_certs_path,
            store_headers=tuple(execution_options.remote_store_headers.items()),
            store_chunk_bytes=execution_options.remote_store_chunk_bytes,
            store_chunk_upload_timeout=execution_options.remote_store_chunk_upload_timeout_seconds,
            store_rpc_retries=execution_options.remote_store_rpc_retries,
            cache_eager_fetch=execution_options.remote_cache_eager_fetch,
            execution_extra_platform_properties=tuple(
                tuple(pair.split("=", 1))
                for pair in execution_options.remote_execution_extra_platform_properties
            ),
            execution_headers=tuple(execution_options.remote_execution_headers.items()),
            execution_overall_deadline_secs=execution_options.remote_execution_overall_deadline_secs,
        )

        exec_stategy_opts = PyExecutionStrategyOptions(
            local_parallelism=execution_options.process_execution_local_parallelism,
            remote_parallelism=execution_options.process_execution_remote_parallelism,
            cleanup_local_dirs=execution_options.process_execution_cleanup_local_dirs,
            use_local_cache=execution_options.process_execution_use_local_cache,
            remote_cache_read=execution_options.remote_cache_read,
            remote_cache_write=execution_options.remote_cache_write,
        )

        return cast(
            PyScheduler,
            self.lib.scheduler_create(
                executor,
                tasks,
                types,
                # Project tree.
                build_root,
                local_store_dir,
                local_execution_root_dir,
                named_caches_dir,
                ca_certs_path,
                ignore_patterns,
                use_gitignore,
                remoting_options,
                exec_stategy_opts,
            ),
        )
