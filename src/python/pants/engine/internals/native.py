# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import logging
import os
import sys
from contextlib import closing
from types import CoroutineType
from typing import Dict, Iterable, List, Tuple, cast

import pkg_resources
from typing_extensions import Protocol

from pants.base.exiter import ExitCode
from pants.base.project_tree import Dir, File, Link
from pants.engine.addresses import Address
from pants.engine.fs import (
    AddPrefix,
    Digest,
    FileContent,
    FilesContent,
    InputFilesContent,
    MaterializeDirectoriesResult,
    MaterializeDirectoryResult,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
    SnapshotSubset,
    UrlToFetch,
)
from pants.engine.interactive_process import InteractiveProcess, InteractiveProcessResult
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResultWithPlatform, MultiPlatformProcess
from pants.engine.selectors import Get
from pants.engine.unions import union
from pants.util.dirutil import safe_mkdtemp
from pants.util.memo import memoized_property
from pants.util.meta import SingletonMetaclass

logger = logging.getLogger(__name__)


NATIVE_ENGINE_MODULE = "native_engine"


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

    def generator_send(self, func, arg):
        """Given a generator, send it the given value and return a response."""
        if self._do_raise_keyboardinterrupt:
            raise KeyboardInterrupt("ctrl-c interrupted execution of a ffi method!")
        try:
            res = func.send(arg)

            if Get.isinstance(res):
                # Get.
                return self.lib.PyGeneratorResponseGet(
                    res.product_type, res.subject_declared_type, res.subject,
                )
            elif type(res) in (tuple, list):
                # GetMulti.
                return self.lib.PyGeneratorResponseGetMulti(
                    tuple(
                        self.lib.PyGeneratorResponseGet(
                            get.product_type, get.subject_declared_type, get.subject,
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
            return self.lib.PyGeneratorResponseBreak(e.value)


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
        self._executor = self.lib.PyExecutor()

    class BinaryLocationError(Exception):
        pass

    @memoized_property
    def _binary(self):
        """Load and return the path to the native engine binary."""
        lib_name = "{}.so".format(NATIVE_ENGINE_MODULE)
        lib_path = os.path.join(safe_mkdtemp(), lib_name)
        try:
            with closing(pkg_resources.resource_stream(__name__, lib_name)) as input_fp:
                # NB: The header stripping code here must be coordinated with header insertion code in
                #     build-support/bin/native/bootstrap_code.sh
                engine_version = input_fp.readline().decode().strip()
                repo_version = input_fp.readline().decode().strip()
                logger.debug("using {} built at {}".format(engine_version, repo_version))
                with open(lib_path, "wb") as output_fp:
                    output_fp.write(input_fp.read())
        except (IOError, OSError) as e:
            raise self.BinaryLocationError(
                "Error unpacking the native engine binary to path {}: {}".format(lib_path, e), e
            )
        return lib_path

    @memoized_property
    def lib(self):
        """Load the native engine as a python module."""
        native_bin_dir = os.path.dirname(self._binary)
        logger.debug("loading native engine python module from: %s", native_bin_dir)
        sys.path.insert(0, native_bin_dir)
        return importlib.import_module(NATIVE_ENGINE_MODULE)

    def decompress_tarball(self, tarfile_path, dest_dir):
        return self.lib.decompress_tarball(tarfile_path, dest_dir)

    def init_rust_logging(self, level, log_show_rust_3rdparty):
        return self.lib.init_logging(level, log_show_rust_3rdparty)

    def setup_pantsd_logger(self, log_file_path, level):
        return self.lib.setup_pantsd_logger(log_file_path, level)

    def setup_stderr_logger(self, level):
        return self.lib.setup_stderr_logger(level)

    def write_log(self, msg: str, *, level: int, target: str):
        """Proxy a log message to the Rust logging faculties."""
        return self.lib.write_log(msg, level, target)

    def write_stdout(self, session, msg: str):
        return self.lib.write_stdout(session, msg)

    def write_stderr(self, session, msg: str):
        return self.lib.write_stderr(session, msg)

    def flush_log(self):
        return self.lib.flush_log()

    def override_thread_logging_destination_to_just_pantsd(self):
        self.lib.override_thread_logging_destination("pantsd")

    def override_thread_logging_destination_to_just_stderr(self):
        self.lib.override_thread_logging_destination("stderr")

    def match_path_globs(self, path_globs: PathGlobs, paths: Iterable[str]) -> bool:
        return cast(bool, self.lib.match_path_globs(path_globs, tuple(paths)))

    def nailgun_server_await_shutdown(self, nailgun_server) -> None:
        """Blocks until the server has shut down.

        Raises an exception if the server exited abnormally
        """
        self.lib.nailgun_server_await_shutdown(self._executor, nailgun_server)

    def new_nailgun_server(self, port: int, runner: RawFdRunner):
        """Creates a nailgun server with a requested port.

        Returns the server and the actual port it bound to.
        """
        return self.lib.nailgun_server_create(self._executor, port, runner)

    def new_tasks(self):
        return self.lib.PyTasks()

    def new_execution_request(self):
        return self.lib.PyExecutionRequest()

    def new_session(
        self,
        scheduler,
        should_record_zipkin_spans,
        dynamic_ui: bool,
        build_id,
        should_report_workunits: bool,
    ):
        return self.lib.PySession(
            scheduler, should_record_zipkin_spans, dynamic_ui, build_id, should_report_workunits,
        )

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
    ):
        """Create and return a native Scheduler."""

        # TODO: There is no longer a need to differentiate constructors from types, as types are
        # callable as well with the cpython crate.
        engine_types = self.lib.PyTypes(
            construct_directory_digest=Digest,
            directory_digest=Digest,
            construct_snapshot=Snapshot,
            snapshot=Snapshot,
            construct_file_content=FileContent,
            construct_files_content=FilesContent,
            files_content=FilesContent,
            construct_process_result=FallibleProcessResultWithPlatform,
            construct_materialize_directories_results=MaterializeDirectoriesResult,
            construct_materialize_directory_result=MaterializeDirectoryResult,
            address=Address,
            path_globs=PathGlobs,
            merge_digests=MergeDigests,
            add_prefix=AddPrefix,
            remove_prefix=RemovePrefix,
            input_files_content=InputFilesContent,
            dir=Dir,
            file=File,
            link=Link,
            platform=Platform,
            multi_platform_process=MultiPlatformProcess,
            process_result=FallibleProcessResultWithPlatform,
            coroutine=CoroutineType,
            url_to_fetch=UrlToFetch,
            string=str,
            bytes=bytes,
            construct_interactive_process_result=InteractiveProcessResult,
            interactive_process=InteractiveProcess,
            interactive_process_result=InteractiveProcessResult,
            snapshot_subset=SnapshotSubset,
            construct_platform=Platform,
        )

        return self.lib.scheduler_create(
            self._executor,
            tasks,
            engine_types,
            # Project tree.
            build_root,
            local_store_dir,
            local_execution_root_dir,
            named_caches_dir,
            ignore_patterns,
            use_gitignore,
            root_subject_types,
            # Remote execution config.
            execution_options.remote_execution,
            execution_options.remote_store_server,
            execution_options.remote_execution_server,
            execution_options.remote_execution_process_cache_namespace,
            execution_options.remote_instance_name,
            execution_options.remote_ca_certs_path,
            execution_options.remote_oauth_bearer_token_path,
            execution_options.remote_store_thread_count,
            execution_options.remote_store_chunk_bytes,
            execution_options.remote_store_connection_limit,
            execution_options.remote_store_chunk_upload_timeout_seconds,
            execution_options.remote_store_rpc_retries,
            tuple(
                tuple(pair.split("=", 1))
                for pair in execution_options.remote_execution_extra_platform_properties
            ),
            execution_options.process_execution_local_parallelism,
            execution_options.process_execution_remote_parallelism,
            execution_options.process_execution_cleanup_local_dirs,
            execution_options.process_execution_speculation_delay,
            execution_options.process_execution_speculation_strategy,
            execution_options.process_execution_use_local_cache,
            tuple((k, v) for (k, v) in execution_options.remote_execution_headers.items()),
            execution_options.remote_execution_enable_streaming,
            execution_options.remote_execution_overall_deadline_secs,
            execution_options.process_execution_local_enable_nailgun,
        )

    def set_panic_handler(self):
        if os.getenv("RUST_BACKTRACE", "0") == "0":
            # The panic handler hides a lot of rust tracing which may be useful.
            # Don't activate it when the user explicitly asks for rust backtraces.
            self.lib.set_panic_handler()
