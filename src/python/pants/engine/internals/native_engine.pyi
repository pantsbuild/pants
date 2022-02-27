# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from io import RawIOBase
from typing import Any, Iterable, Sequence, TextIO, Tuple

from typing_extensions import Protocol

from pants.engine.fs import PathGlobs
from pants.engine.internals.scheduler import Workunit, _PathGlobsAndRootCollection
from pants.engine.internals.session import SessionValues
from pants.engine.process import InteractiveProcessResult

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

# ------------------------------------------------------------------------------
# Address (parsing)
# ------------------------------------------------------------------------------

class AddressParseException(Exception):
    pass

def address_parse(spec: str) -> tuple[str, str | None, tuple[tuple[str, str], ...], str | None]: ...

# ------------------------------------------------------------------------------
# Scheduler
# ------------------------------------------------------------------------------

class PyExecutor:
    def __init__(self, core_threads: int, max_threads: int) -> None: ...

# ------------------------------------------------------------------------------
# FS
# ------------------------------------------------------------------------------

class Digest:
    """A Digest is a lightweight reference to a set of files known about by the engine.

    You can use `await Get(Snapshot, Digest)` to see the file names referred to, or use `await
    Get(DigestContents, Digest)` to see the actual file content.
    """

    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: Digest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class FileDigest:
    """A FileDigest is a digest that refers to a file's content, without its name."""

    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: FileDigest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class Snapshot:
    """A Snapshot is a collection of sorted file paths and dir paths fingerprinted by their
    names/content.

    You can lift a `Digest` to a `Snapshot` with `await Get(Snapshot, Digest, my_digest)`.
    """

    @classmethod
    def _unsafe_create(
        cls, digest: Digest, files: Sequence[str], dirs: Sequence[str]
    ) -> Snapshot: ...
    @property
    def digest(self) -> Digest: ...
    @property
    def dirs(self) -> tuple[str, ...]: ...
    @property
    def files(self) -> tuple[str, ...]: ...
    def __eq__(self, other: Snapshot | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class MergeDigests:
    """A request to merge several digests into one single digest.

    This will fail if there are any conflicting changes, such as two digests having the same
    file but with different content.

    Example:

        result = await Get(Digest, MergeDigests([digest1, digest2])
    """

    def __init__(self, digests: Iterable[Digest]) -> None: ...
    def __eq__(self, other: MergeDigests | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class AddPrefix:
    """A request to add the specified prefix path to every file and directory in the digest.

    Example:

        result = await Get(Digest, AddPrefix(input_digest, "my_dir")
    """

    def __init__(self, digest: Digest, prefix: str) -> None: ...
    def __eq__(self, other: AddPrefix | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class RemovePrefix:
    """A request to remove the specified prefix path from every file and directory in the digest.

    This will fail if there are any files or directories in the original input digest without the
    specified prefix.

    Example:

        result = await Get(Digest, RemovePrefix(input_digest, "my_dir")
    """

    def __init__(self, digest: Digest, prefix: str) -> None: ...
    def __eq__(self, other: RemovePrefix | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

EMPTY_DIGEST: Digest
EMPTY_FILE_DIGEST: FileDigest
EMPTY_SNAPSHOT: Snapshot

def default_cache_path() -> str: ...

# TODO: Really, `paths` should be `Sequence[str]`. Fix and update call sites so that we don't
#  cast to `tuple()` when not necessary.
def match_path_globs(path_globs: PathGlobs, paths: tuple[str, ...]) -> str: ...

# ------------------------------------------------------------------------------
# Workunits
# ------------------------------------------------------------------------------

def all_counter_names() -> list[str]: ...

# ------------------------------------------------------------------------------
# Nailgun
# ------------------------------------------------------------------------------

class PyNailgunClient:
    def __init__(self, port: int, executor: PyExecutor) -> None: ...
    def execute(self, command: str, args: list[str], env: dict[str, str]) -> int: ...

class PantsdConnectionException(Exception):
    pass

class PantsdClientException(Exception):
    pass

# ------------------------------------------------------------------------------
# Testutil
# ------------------------------------------------------------------------------

class PyStubCASBuilder:
    def always_errors(self) -> PyStubCASBuilder: ...
    def build(self, executor: PyExecutor) -> PyStubCAS: ...

class PyStubCAS:
    @classmethod
    def builder(cls) -> PyStubCASBuilder: ...
    @property
    def address(self) -> str: ...

class RawFdRunner(Protocol):
    def __call__(
        self,
        command: str,
        args: tuple[str, ...],
        env: dict[str, str],
        cancellation_latch: PySessionCancellationLatch,
        stdin_fileno: int,
        stdout_fileno: int,
        stderr_fileno: int,
    ) -> int: ...

def capture_snapshots(
    scheduler: PyScheduler,
    session: PySession,
    path_globs_and_root_tuple_wrapper: _PathGlobsAndRootCollection,
) -> list[Snapshot]: ...
def ensure_remote_has_recursive(
    scheduler: PyScheduler, digests: list[Digest | FileDigest]
) -> None: ...
def single_file_digests_to_bytes(
    scheduler: PyScheduler, digests: list[FileDigest]
) -> list[bytes]: ...
def write_digest(
    scheduler: PyScheduler, session: PySession, digest: Digest, path_prefix: str
) -> None: ...
def write_log(msg: str, level: int, target: str) -> None: ...
def flush_log() -> None: ...
def set_per_run_log_path(path: str | None) -> None: ...
def maybe_set_panic_handler() -> None: ...
def stdio_initialize(
    level: int,
    show_rust_3rdparty_logs: bool,
    show_target: bool,
    log_levels_by_target: dict[str, int],
    literal_filters: tuple[str, ...],
    regex_filters: tuple[str, ...],
    log_file: str,
) -> tuple[RawIOBase, TextIO, TextIO]: ...
def stdio_thread_get_destination() -> PyStdioDestination: ...
def stdio_thread_set_destination(destination: PyStdioDestination) -> None: ...
def stdio_thread_console_set(stdin_fileno: int, stdout_fileno: int, stderr_fileno: int) -> None: ...
def stdio_thread_console_color_mode_set(use_color: bool) -> None: ...
def stdio_thread_console_clear() -> None: ...
def stdio_write_stdout(msg: str) -> None: ...
def stdio_write_stderr(msg: str) -> None: ...
def task_side_effected() -> None: ...
def teardown_dynamic_ui(scheduler: PyScheduler, session: PySession) -> None: ...
def tasks_task_begin(
    tasks: PyTasks,
    func: Any,
    return_type: type,
    side_effecting: bool,
    engine_aware_return_type: bool,
    cacheable: bool,
    name: str,
    desc: str,
    level: int,
) -> None: ...
def tasks_task_end(tasks: PyTasks) -> None: ...
def tasks_add_get(tasks: PyTasks, output: type, input: type) -> None: ...
def tasks_add_union(tasks: PyTasks, output_type: type, input_type: tuple[type, ...]) -> None: ...
def tasks_add_select(tasks: PyTasks, selector: type) -> None: ...
def tasks_add_query(tasks: PyTasks, output_type: type, input_type: tuple[type, ...]) -> None: ...
def execution_add_root_select(
    scheduler: PyScheduler,
    execution_request: PyExecutionRequest,
    param_vals: Sequence,
    product: type,
) -> None: ...
def nailgun_server_await_shutdown(server: PyNailgunServer) -> None: ...
def nailgun_server_create(
    executor: PyExecutor, port: int, runner: RawFdRunner
) -> PyNailgunServer: ...
def scheduler_create(
    executor: PyExecutor,
    tasks: PyTasks,
    types: PyTypes,
    build_root: str,
    local_execution_root_dir: str,
    named_caches_dir: str,
    ca_certs_path: str | None,
    ignore_patterns: Sequence[str],
    use_gitignore: bool,
    watch_filesystem: bool,
    remoting_options: PyRemotingOptions,
    local_store_options: PyLocalStoreOptions,
    exec_strategy_opts: PyExecutionStrategyOptions,
) -> PyScheduler: ...
def scheduler_execute(
    scheduler: PyScheduler, session: PySession, execution_request: PyExecutionRequest
) -> list: ...
def scheduler_metrics(scheduler: PyScheduler, session: PySession) -> dict[str, int]: ...
def scheduler_live_items(
    scheduler: PyScheduler, session: PySession
) -> tuple[list[Any], dict[str, tuple[int, int]]]: ...
def scheduler_shutdown(scheduler: PyScheduler, timeout_secs: int) -> None: ...
def session_new_run_id(session: PySession) -> None: ...
def session_poll_workunits(
    scheduler: PyScheduler, session: PySession, max_log_verbosity_level: int
) -> tuple[tuple[Workunit, ...], tuple[Workunit, ...]]: ...
def session_run_interactive_process(
    session: PySession, InteractiveProcess
) -> InteractiveProcessResult: ...
def session_get_observation_histograms(scheduler: PyScheduler, session: PySession) -> dict: ...
def session_record_test_observation(
    scheduler: PyScheduler, session: PySession, value: int
) -> None: ...
def session_isolated_shallow_clone(session: PySession, build_id: str) -> PySession: ...
def graph_len(scheduler: PyScheduler) -> int: ...
def graph_visualize(scheduler: PyScheduler, session: PySession, path: str) -> None: ...
def graph_invalidate_paths(scheduler: PyScheduler, paths: Iterable[str]) -> int: ...
def graph_invalidate_all_paths(scheduler: PyScheduler) -> int: ...
def graph_invalidate_all(scheduler: PyScheduler) -> None: ...
def check_invalidation_watcher_liveness(scheduler: PyScheduler) -> None: ...
def validate_reachability(scheduler: PyScheduler) -> None: ...
def rule_graph_consumed_types(
    scheduler: PyScheduler, param_types: Sequence[type], product_type: type
) -> list[type]: ...
def rule_graph_visualize(scheduler: PyScheduler, path: str) -> None: ...
def rule_subgraph_visualize(
    scheduler: PyScheduler, param_types: Sequence[type], product_type: type, path: str
) -> None: ...
def garbage_collect_store(scheduler: PyScheduler, target_size_bytes: int) -> None: ...
def lease_files_in_graph(scheduler: PyScheduler, session: PySession) -> None: ...
def strongly_connected_components(
    adjacency_lists: Sequence[Tuple[Any, Sequence[Any]]]
) -> Sequence[Sequence[Any]]: ...
def hash_prefix_zero_bits(item: str) -> int: ...

class PyExecutionRequest:
    def __init__(
        self, *, poll: bool, poll_delay_in_ms: int | None, timeout_in_ms: int | None
    ) -> None: ...

class PyExecutionStrategyOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyGeneratorResponseBreak:
    def __init__(self, val: Any) -> None: ...

class PyGeneratorResponseGet:
    def __init__(self, product: type, declared_subject: type, subject: Any) -> None: ...

class PyGeneratorResponseGetMulti:
    def __init__(self, gets: tuple[PyGeneratorResponseGet, ...]) -> None: ...

class PyNailgunServer:
    def port(self) -> int: ...

class PyRemotingOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyLocalStoreOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyScheduler:
    pass

class PySession:
    def __init__(
        self,
        *,
        scheduler: PyScheduler,
        dynamic_ui: bool,
        ui_use_prodash: bool,
        build_id: str,
        session_values: SessionValues,
        cancellation_latch: PySessionCancellationLatch,
    ) -> None: ...
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...

class PySessionCancellationLatch:
    def __init__(self) -> None: ...

class PyTasks:
    def __init__(self) -> None: ...

class PyTypes:
    def __init__(self, **kwargs: Any) -> None: ...

class PyStdioDestination:
    pass

class PollTimeout(Exception):
    pass
