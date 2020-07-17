# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from typing import Dict, Iterable, List, Tuple, Union, cast

from typing_extensions import Protocol

from pants.base.exiter import ExitCode
from pants.engine.fs import PathGlobs
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import (
    PyExecutionRequest,
    PyExecutionStrategyOptions,
    PyExecutor,
    PyGeneratorResponseBreak,
    PyGeneratorResponseGet,
    PyGeneratorResponseGetMulti,
    PyNailgunServer,
    PyRemotingOptions,
    PyScheduler,
    PySession,
    PyTasks,
    PyTypes,
)
from pants.engine.selectors import Get
from pants.engine.unions import union
from pants.util.memo import memoized_property
from pants.util.meta import SingletonMetaclass

logger = logging.getLogger(__name__)


class Externs:
    """Methods exposed from Python to Rust.

    TODO: These could be implemented in Rust in `externs.rs` via the cpython API.
    """

    def __init__(self, lib):
        self.lib = lib

    _do_raise_keyboardinterrupt = bool(os.environ.get("_RAISE_KEYBOARDINTERRUPT_IN_EXTERNS", False))

    def is_union(self, input_type):
        """Return whether or not a type is a member of a union."""
        # NB: This check is exposed for testing error handling in CFFI methods. This code path should
        # never be active in normal pants usage.
        return union.is_instance(input_type)

    def create_exception(self, msg):
        """Given a utf8 message string, create an Exception object."""
        return Exception(msg)

    def val_to_str(self, val):
        """Given a `obj`, return str(obj)."""
        return "" if val is None else str(val)

    def generator_send(
        self, func, arg
    ) -> Union[PyGeneratorResponseGet, PyGeneratorResponseGetMulti, PyGeneratorResponseBreak]:
        """Given a generator, send it the given value and return a response."""
        if self._do_raise_keyboardinterrupt:
            raise KeyboardInterrupt("ctrl-c interrupted execution of a ffi method!")
        try:
            res = func.send(arg)

            if isinstance(res, Get):
                # Get.
                return PyGeneratorResponseGet(
                    res.product_type, res.subject_declared_type, res.subject, res.weak,
                )
            elif type(res) in (tuple, list):
                # GetMulti.
                return PyGeneratorResponseGetMulti(
                    tuple(
                        PyGeneratorResponseGet(
                            get.product_type, get.subject_declared_type, get.subject, get.weak,
                        )
                        for get in res
                    )
                )
            else:
                raise ValueError(f"internal engine error: unrecognized coroutine result {res}")
        except StopIteration as e:
            if not e.args:
                raise
            # This was a `return` from a coroutine, as opposed to a `StopIteration` raised
            # by calling `next()` on an empty iterator.
            return PyGeneratorResponseBreak(e.value)


class RawFdRunner(Protocol):
    def __call__(
        self,
        command: str,
        args: Tuple[str, ...],
        env: Dict[str, str],
        working_directory: bytes,
        stdin_fd: int,
        stdout_fd: int,
        stderr_fd: int,
    ) -> ExitCode:
        ...


class Native(metaclass=SingletonMetaclass):
    """Encapsulates fetching a platform specific version of the native portion of the engine."""

    def __init__(self):
        self.externs = Externs(self.lib)
        self.lib.externs_set(self.externs)
        self._executor = PyExecutor()

    class BinaryLocationError(Exception):
        pass

    @memoized_property
    def lib(self):
        """Load the native engine as a python module."""
        return native_engine

    def decompress_tarball(self, tarfile_path, dest_dir):
        return self.lib.decompress_tarball(tarfile_path, dest_dir)

    def init_rust_logging(self, level, log_show_rust_3rdparty: bool, use_color: bool):
        return self.lib.init_logging(level, log_show_rust_3rdparty, use_color)

    def setup_pantsd_logger(self, log_file_path, level):
        return self.lib.setup_pantsd_logger(log_file_path, level)

    def setup_stderr_logger(self, level):
        return self.lib.setup_stderr_logger(level)

    def write_log(self, msg: str, *, level: int, target: str):
        """Proxy a log message to the Rust logging faculties."""
        return self.lib.write_log(msg, level, target)

    def write_stdout(self, scheduler, session, msg: str, teardown_ui: bool):
        if teardown_ui:
            self.teardown_dynamic_ui(scheduler, session)
        return self.lib.write_stdout(session, msg)

    def write_stderr(self, scheduler, session, msg: str, teardown_ui: bool):
        if teardown_ui:
            self.teardown_dynamic_ui(scheduler, session)
        return self.lib.write_stderr(session, msg)

    def teardown_dynamic_ui(self, scheduler, session):
        self.lib.teardown_dynamic_ui(scheduler, session)

    def flush_log(self):
        return self.lib.flush_log()

    def override_thread_logging_destination_to_just_pantsd(self):
        self.lib.override_thread_logging_destination("pantsd")

    def override_thread_logging_destination_to_just_stderr(self):
        self.lib.override_thread_logging_destination("stderr")

    def match_path_globs(self, path_globs: PathGlobs, paths: Iterable[str]) -> Tuple[str, ...]:
        """Return all paths that match the PathGlobs."""
        return tuple(self.lib.match_path_globs(path_globs, tuple(paths)))

    def nailgun_server_await_shutdown(self, nailgun_server) -> None:
        """Blocks until the server has shut down.

        Raises an exception if the server exited abnormally
        """
        self.lib.nailgun_server_await_shutdown(self._executor, nailgun_server)

    def new_nailgun_server(self, port: int, runner: RawFdRunner) -> PyNailgunServer:
        """Creates a nailgun server with a requested port.

        Returns the server and the actual port it bound to.
        """
        return cast(PyNailgunServer, self.lib.nailgun_server_create(self._executor, port, runner))

    def new_tasks(self) -> PyTasks:
        return PyTasks()

    def new_execution_request(self) -> PyExecutionRequest:
        return PyExecutionRequest()

    def new_session(
        self, scheduler, dynamic_ui: bool, build_id, should_report_workunits: bool,
    ) -> PySession:
        return PySession(scheduler, dynamic_ui, build_id, should_report_workunits,)

    def new_scheduler(
        self,
        tasks,
        root_subject_types,
        build_root: str,
        local_store_dir: str,
        local_execution_root_dir: str,
        named_caches_dir: str,
        ignore_patterns: List[str],
        use_gitignore: bool,
        execution_options,
        types: PyTypes,
    ) -> PyScheduler:
        """Create and return a native Scheduler."""

        remoting_options = PyRemotingOptions(
            execution_enable=execution_options.remote_execution,
            store_servers=execution_options.remote_store_server,
            execution_server=execution_options.remote_execution_server,
            execution_process_cache_namespace=execution_options.remote_execution_process_cache_namespace,
            instance_name=execution_options.remote_instance_name,
            root_ca_certs_path=execution_options.remote_ca_certs_path,
            oauth_bearer_token_path=execution_options.remote_oauth_bearer_token_path,
            store_thread_count=execution_options.remote_store_thread_count,
            store_chunk_bytes=execution_options.remote_store_chunk_bytes,
            store_chunk_upload_timeout=execution_options.remote_store_connection_limit,
            store_rpc_retries=execution_options.remote_store_chunk_upload_timeout_seconds,
            store_connection_limit=execution_options.remote_store_rpc_retries,
            execution_extra_platform_properties=tuple(
                tuple(pair.split("=", 1))
                for pair in execution_options.remote_execution_extra_platform_properties
            ),
            execution_headers=tuple(
                (k, v) for (k, v) in execution_options.remote_execution_headers.items()
            ),
            execution_overall_deadline_secs=execution_options.remote_execution_overall_deadline_secs,
        )

        exec_stategy_opts = PyExecutionStrategyOptions(
            local_parallelism=execution_options.process_execution_local_parallelism,
            remote_parallelism=execution_options.process_execution_remote_parallelism,
            cleanup_local_dirs=execution_options.process_execution_cleanup_local_dirs,
            speculation_delay=execution_options.process_execution_speculation_delay,
            speculation_strategy=execution_options.process_execution_speculation_strategy,
            use_local_cache=execution_options.process_execution_use_local_cache,
            local_enable_nailgun=execution_options.process_execution_local_enable_nailgun,
        )

        return self.lib.scheduler_create(
            self._executor,
            tasks,
            types,
            # Project tree.
            build_root,
            local_store_dir,
            local_execution_root_dir,
            named_caches_dir,
            ignore_patterns,
            use_gitignore,
            root_subject_types,
            remoting_options,
            exec_stategy_opts,
        )

    def set_panic_handler(self):
        if os.getenv("RUST_BACKTRACE", "0") == "0":
            # The panic handler hides a lot of rust tracing which may be useful.
            # Don't activate it when the user explicitly asks for rust backtraces.
            self.lib.set_panic_handler()
