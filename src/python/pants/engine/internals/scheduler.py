# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import PurePath
from types import CoroutineType
from typing import Any, Callable, Dict, Iterable, NoReturn, Sequence, cast

from typing_extensions import TypedDict

from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType, SideEffecting
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    Directory,
    FileContent,
    FileDigest,
    FileEntry,
    NativeDownloadFile,
    PathGlobs,
    PathGlobsAndRoot,
    PathMetadataRequest,
    PathMetadataResult,
    Paths,
    Snapshot,
    SymlinkEntry,
)
from pants.engine.goal import CurrentExecutingGoals, Goal
from pants.engine.internals import native_engine
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.internals.native_dep_inference import (
    NativeParsedDockerfileInfo,
    NativeParsedJavascriptDependencies,
    NativeParsedPythonDependencies,
    ParsedJavascriptDependencyCandidate,
)
from pants.engine.internals.native_engine import (
    PyExecutionRequest,
    PyExecutionStrategyOptions,
    PyExecutor,
    PyLocalStoreOptions,
    PyRemotingOptions,
    PyScheduler,
    PySession,
    PySessionCancellationLatch,
    PyTasks,
    PyTypes,
)
from pants.engine.internals.nodes import Return, Throw
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import RunId, SessionValues
from pants.engine.platform import Platform
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
    ProcessResultMetadata,
)
from pants.engine.rules import Rule, RuleIndex, TaskRule
from pants.engine.unions import UnionMembership, is_union, union_in_scope_types
from pants.option.global_options import (
    LOCAL_STORE_LEASE_TIME_SECS,
    ExecutionOptions,
    LocalStoreOptions,
)
from pants.util.contextutil import temporary_file_path
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


Workunit = Dict[str, Any]


class PolledWorkunits(TypedDict):
    started: tuple[Workunit, ...]
    completed: tuple[Workunit, ...]


@dataclass(frozen=True)
class ExecutionRequest:
    """Holds the roots for an execution, which might have been requested by a user.

    To create an ExecutionRequest, see `SchedulerSession.execution_request`.
    """

    roots: tuple[tuple[type, Any | Params], ...]
    native: PyExecutionRequest


class ExecutionError(Exception):
    def __init__(self, message, wrapped_exceptions=None):
        super().__init__(message)
        self.wrapped_exceptions = wrapped_exceptions or ()


class ExecutionTimeoutError(ExecutionError):
    """An ExecutionRequest specified a timeout which elapsed before the request completed."""


class Scheduler:
    def __init__(
        self,
        *,
        ignore_patterns: list[str],
        use_gitignore: bool,
        build_root: str,
        local_execution_root_dir: str,
        named_caches_dir: str,
        ca_certs_path: str | None,
        rules: Iterable[Rule],
        union_membership: UnionMembership,
        execution_options: ExecutionOptions,
        local_store_options: LocalStoreOptions,
        executor: PyExecutor,
        include_trace_on_error: bool = True,
        visualize_to_dir: str | None = None,
        validate_reachability: bool = True,
        watch_filesystem: bool = True,
    ) -> None:
        """
        :param ignore_patterns: A list of gitignore-style file patterns for pants to ignore.
        :param use_gitignore: If set, pay attention to .gitignore files.
        :param build_root: The build root as a string.
        :param local_execution_root_dir: The directory to use for local execution sandboxes.
        :param named_caches_dir: The directory to use as the root for named mutable caches.
        :param ca_certs_path: Path to pem file for custom CA, if needed.
        :param rules: A set of Rules which is used to compute values in the graph.
        :param union_membership: All the registered and normalized union rules.
        :param execution_options: Execution options for (remote) processes.
        :param local_store_options: Options for the engine's LMDB store(s).
        :param include_trace_on_error: Include the trace through the graph upon encountering errors.
        :param validate_reachability: True to assert that all rules in an otherwise successfully
          constructed rule graph are reachable: if a graph cannot be successfully constructed, it
          is always a fatal error.
        :param watch_filesystem: False if filesystem watching should be disabled.
        """
        self.include_trace_on_error = include_trace_on_error
        self._visualize_to_dir = visualize_to_dir
        self._visualize_run_count = 0
        # Validate and register all provided and intrinsic tasks.
        rule_index = RuleIndex.create(rules)
        tasks = register_rules(rule_index, union_membership)

        # Create the native Scheduler and Session.
        types = PyTypes(
            paths=Paths,
            path_metadata_request=PathMetadataRequest,
            path_metadata_result=PathMetadataResult,
            file_content=FileContent,
            file_entry=FileEntry,
            symlink_entry=SymlinkEntry,
            directory=Directory,
            digest_contents=DigestContents,
            digest_entries=DigestEntries,
            path_globs=PathGlobs,
            create_digest=CreateDigest,
            digest_subset=DigestSubset,
            native_download_file=NativeDownloadFile,
            platform=Platform,
            process=Process,
            process_result=FallibleProcessResult,
            process_result_metadata=ProcessResultMetadata,
            coroutine=CoroutineType,
            session_values=SessionValues,
            run_id=RunId,
            interactive_process=InteractiveProcess,
            interactive_process_result=InteractiveProcessResult,
            engine_aware_parameter=EngineAwareParameter,
            docker_resolve_image_request=DockerResolveImageRequest,
            docker_resolve_image_result=DockerResolveImageResult,
            parsed_python_deps_result=NativeParsedPythonDependencies,
            parsed_javascript_deps_result=NativeParsedJavascriptDependencies,
            parsed_dockerfile_info_result=NativeParsedDockerfileInfo,
            parsed_javascript_deps_candidate_result=ParsedJavascriptDependencyCandidate,
        )
        remoting_options = PyRemotingOptions(
            provider=execution_options.remote_provider.value,
            execution_enable=execution_options.remote_execution,
            store_headers=execution_options.remote_store_headers,
            store_chunk_bytes=execution_options.remote_store_chunk_bytes,
            store_rpc_retries=execution_options.remote_store_rpc_retries,
            store_rpc_concurrency=execution_options.remote_store_rpc_concurrency,
            store_rpc_timeout_millis=execution_options.remote_store_rpc_timeout_millis,
            store_batch_api_size_limit=execution_options.remote_store_batch_api_size_limit,
            cache_warnings_behavior=execution_options.remote_cache_warnings.value,
            cache_content_behavior=execution_options.cache_content_behavior.value,
            cache_rpc_concurrency=execution_options.remote_cache_rpc_concurrency,
            cache_rpc_timeout_millis=execution_options.remote_cache_rpc_timeout_millis,
            execution_headers=execution_options.remote_execution_headers,
            execution_overall_deadline_secs=execution_options.remote_execution_overall_deadline_secs,
            execution_rpc_concurrency=execution_options.remote_execution_rpc_concurrency,
            store_address=execution_options.remote_store_address,
            execution_address=execution_options.remote_execution_address,
            execution_process_cache_namespace=execution_options.process_execution_cache_namespace,
            instance_name=execution_options.remote_instance_name,
            root_ca_certs_path=execution_options.remote_ca_certs_path,
            client_certs_path=execution_options.remote_client_certs_path,
            client_key_path=execution_options.remote_client_key_path,
            append_only_caches_base_path=execution_options.remote_execution_append_only_caches_base_path,
        )
        py_local_store_options = PyLocalStoreOptions(
            store_dir=local_store_options.store_dir,
            process_cache_max_size_bytes=local_store_options.processes_max_size_bytes,
            files_max_size_bytes=local_store_options.files_max_size_bytes,
            directories_max_size_bytes=local_store_options.directories_max_size_bytes,
            lease_time_millis=LOCAL_STORE_LEASE_TIME_SECS * 1000,
            shard_count=local_store_options.shard_count,
        )
        exec_strategy_opts = PyExecutionStrategyOptions(
            local_cache=execution_options.local_cache,
            remote_cache_read=execution_options.remote_cache_read,
            remote_cache_write=execution_options.remote_cache_write,
            local_keep_sandboxes=execution_options.keep_sandboxes.value,
            local_parallelism=execution_options.process_execution_local_parallelism,
            local_enable_nailgun=execution_options.process_execution_local_enable_nailgun,
            remote_parallelism=execution_options.process_execution_remote_parallelism,
            child_max_memory=execution_options.process_total_child_memory_usage or 0,
            child_default_memory=execution_options.process_per_child_memory_usage,
            graceful_shutdown_timeout=execution_options.process_execution_graceful_shutdown_timeout,
        )

        self._py_executor = executor
        self._py_scheduler = native_engine.scheduler_create(
            executor,
            tasks,
            types,
            build_root,
            local_execution_root_dir,
            named_caches_dir,
            ignore_patterns,
            use_gitignore,
            watch_filesystem,
            remoting_options,
            py_local_store_options,
            exec_strategy_opts,
            ca_certs_path,
        )

        # If configured, visualize the rule graph before asserting that it is valid.
        if self._visualize_to_dir is not None:
            rule_graph_name = "rule_graph.dot"
            self.visualize_rule_graph_to_file(os.path.join(self._visualize_to_dir, rule_graph_name))

        if validate_reachability:
            native_engine.validate_reachability(self.py_scheduler)

    @property
    def py_scheduler(self) -> PyScheduler:
        return self._py_scheduler

    @property
    def py_executor(self) -> PyExecutor:
        return self._py_executor

    def _to_params_list(self, subject_or_params: Any | Params) -> Sequence[Any]:
        if isinstance(subject_or_params, Params):
            return subject_or_params.params
        return [subject_or_params]

    def visualize_rule_graph_to_file(self, filename: str) -> None:
        native_engine.rule_graph_visualize(self.py_scheduler, filename)

    def visualize_rule_subgraph_to_file(
        self, filename: str, root_subject_types: list[type], product_type: type
    ) -> None:
        native_engine.rule_subgraph_visualize(
            self.py_scheduler, root_subject_types, product_type, filename
        )

    def rule_graph_visualization(self):
        with temporary_file_path() as path:
            self.visualize_rule_graph_to_file(path)
            with open(path) as fd:
                for line in fd.readlines():
                    yield line.rstrip()

    def rule_subgraph_visualization(self, root_subject_types: list[type], product_type: type):
        with temporary_file_path() as path:
            self.visualize_rule_subgraph_to_file(path, root_subject_types, product_type)
            with open(path) as fd:
                for line in fd.readlines():
                    yield line.rstrip()

    def rule_graph_consumed_types(
        self, root_subject_types: Sequence[type], product_type: type
    ) -> Sequence[type]:
        return native_engine.rule_graph_consumed_types(
            self.py_scheduler, root_subject_types, product_type
        )

    def invalidate_files(self, filenames: Iterable[str]) -> int:
        return native_engine.graph_invalidate_paths(self.py_scheduler, filenames)

    def invalidate_all_files(self) -> int:
        return native_engine.graph_invalidate_all_paths(self.py_scheduler)

    def invalidate_all(self) -> None:
        native_engine.graph_invalidate_all(self.py_scheduler)

    def check_invalidation_watcher_liveness(self) -> None:
        native_engine.check_invalidation_watcher_liveness(self.py_scheduler)

    def graph_len(self) -> int:
        return native_engine.graph_len(self.py_scheduler)

    def execution_add_root_select(
        self, execution_request: PyExecutionRequest, subject_or_params: Any | Params, product: type
    ) -> None:
        params = self._to_params_list(subject_or_params)
        native_engine.execution_add_root_select(
            self.py_scheduler, execution_request, params, product
        )

    @property
    def visualize_to_dir(self) -> str | None:
        return self._visualize_to_dir

    def garbage_collect_store(self, target_size_bytes: int) -> None:
        native_engine.garbage_collect_store(self.py_scheduler, target_size_bytes)

    def new_session(
        self,
        build_id: str,
        dynamic_ui: bool = False,
        ui_use_prodash: bool = False,
        max_workunit_level: LogLevel = LogLevel.DEBUG,
        session_values: SessionValues | None = None,
        cancellation_latch: PySessionCancellationLatch | None = None,
    ) -> SchedulerSession:
        """Creates a new SchedulerSession for this Scheduler."""
        return SchedulerSession(
            self,
            PySession(
                scheduler=self.py_scheduler,
                dynamic_ui=dynamic_ui,
                ui_use_prodash=ui_use_prodash,
                max_workunit_level=max_workunit_level.level,
                build_id=build_id,
                session_values=session_values or SessionValues(),
                cancellation_latch=cancellation_latch or PySessionCancellationLatch(),
            ),
        )

    def shutdown(self, timeout_secs: int = 60) -> None:
        native_engine.scheduler_shutdown(self.py_scheduler, timeout_secs)


class _PathGlobsAndRootCollection(Collection[PathGlobsAndRoot]):
    pass


class SchedulerSession:
    """A handle to a shared underlying Scheduler and a unique Session.

    Generally a Session corresponds to a single run of pants: some metrics are specific to a
    Session.
    """

    def __init__(self, scheduler: Scheduler, session: PySession) -> None:
        self._scheduler = scheduler
        self._py_session = session
        self._goals = session.session_values.get(CurrentExecutingGoals) or CurrentExecutingGoals()

    @property
    def scheduler(self) -> Scheduler:
        return self._scheduler

    @property
    def py_scheduler(self) -> PyScheduler:
        return self._scheduler.py_scheduler

    @property
    def py_session(self) -> PySession:
        return self._py_session

    def isolated_shallow_clone(self, build_id: str) -> SchedulerSession:
        return SchedulerSession(
            self._scheduler,
            native_engine.session_isolated_shallow_clone(self._py_session, build_id),
        )

    def poll_workunits(self, max_log_verbosity: LogLevel) -> PolledWorkunits:
        result = native_engine.session_poll_workunits(
            self.py_scheduler, self.py_session, max_log_verbosity.level
        )
        return {"started": result[0], "completed": result[1]}

    def new_run_id(self) -> None:
        """Assigns a new "run id" to this Session, without creating a new Session.

        Usually each Session corresponds to one end user "run", but there are exceptions: notably,
        the `--loop` feature uses one Session, but would like to observe new values for uncacheable
        nodes in each iteration of its loop.
        """
        native_engine.session_new_run_id(self.py_session)

    def visualize_graph_to_file(self, filename: str) -> None:
        """Visualize a graph walk by writing graphviz `dot` output to a file."""
        native_engine.graph_visualize(self.py_scheduler, self.py_session, filename)

    def visualize_rule_graph_to_file(self, filename: str) -> None:
        self._scheduler.visualize_rule_graph_to_file(filename)

    def rule_graph_rule_gets(self) -> dict[Callable, list[tuple[type, list[type], Callable]]]:
        return native_engine.rule_graph_rule_gets(self.py_scheduler)

    def execution_request(
        self,
        requests: Sequence[tuple[type, Any | Params]],
        poll: bool = False,
        poll_delay: float | None = None,
        timeout: float | None = None,
    ) -> ExecutionRequest:
        """Create and return an ExecutionRequest for the given (product, subject) pairs.

        :param requests: A sequence of product types to request for subjects.
        :param poll: True to wait for _all_ of the given roots to
          have changed since their last observed values in this SchedulerSession.
        :param poll_delay: A delay (in seconds) to wait after observing a change, and before
          beginning to compute a new value.
        :param timeout: An optional timeout to wait for the request to complete (in seconds). If the
          request has not completed before the timeout has elapsed, ExecutionTimeoutError is raised.
        :returns: An ExecutionRequest for the given products and subjects.
        """
        native_execution_request = PyExecutionRequest(
            poll=poll,
            poll_delay_in_ms=int(poll_delay * 1000) if poll_delay else None,
            timeout_in_ms=int(timeout * 1000) if timeout else None,
        )
        for product, subject in requests:
            self._scheduler.execution_add_root_select(native_execution_request, subject, product)
        return ExecutionRequest(tuple(requests), native_execution_request)

    def invalidate_files(self, direct_filenames: Iterable[str]) -> int:
        """Invalidates the given filenames in an internal product Graph instance."""
        invalidated = self._scheduler.invalidate_files(direct_filenames)
        self._maybe_visualize()
        return invalidated

    def invalidate_all_files(self) -> int:
        """Invalidates all filenames in an internal product Graph instance."""
        invalidated = self._scheduler.invalidate_all_files()
        self._maybe_visualize()
        return invalidated

    def metrics(self) -> dict[str, int]:
        """Returns metrics for this SchedulerSession as a dict of metric name to metric value."""
        return native_engine.scheduler_metrics(self.py_scheduler, self.py_session)

    def live_items(self) -> tuple[list[Any], dict[str, tuple[int, int]]]:
        """Return all Python objects held by the Scheduler."""
        return native_engine.scheduler_live_items(self.py_scheduler, self.py_session)

    def _maybe_visualize(self) -> None:
        if self._scheduler.visualize_to_dir is not None:
            # TODO: This increment-and-get is racey.
            name = f"graph.{self._scheduler._visualize_run_count:03d}.dot"
            self._scheduler._visualize_run_count += 1
            logger.info(f"Visualizing graph as {name}")
            self.visualize_graph_to_file(os.path.join(self._scheduler.visualize_to_dir, name))

    def teardown_dynamic_ui(self) -> None:
        native_engine.teardown_dynamic_ui(self.py_scheduler, self.py_session)

    def _execute(
        self, execution_request: ExecutionRequest
    ) -> tuple[tuple[tuple[Any, Return], ...], tuple[tuple[Any, Throw], ...]]:
        start_time = time.time()
        try:
            raw_roots = native_engine.scheduler_execute(
                self.py_scheduler,
                self.py_session,
                execution_request.native,
            )
        except native_engine.PollTimeout:
            raise ExecutionTimeoutError("Timed out")

        states = [
            Throw(
                raw_root.result,
                python_traceback=raw_root.python_traceback,
                engine_traceback=raw_root.engine_traceback,
            )
            if raw_root.is_throw
            else Return(raw_root.result)
            for raw_root in raw_roots
        ]

        roots = list(zip(execution_request.roots, states))

        self._maybe_visualize()
        logger.debug(
            "computed %s nodes in %f seconds. there are %s total nodes.",
            len(roots),
            time.time() - start_time,
            self._scheduler.graph_len(),
        )

        returns = tuple((root, state) for root, state in roots if isinstance(state, Return))
        throws = tuple((root, state) for root, state in roots if isinstance(state, Throw))
        return returns, throws

    def _raise_on_error(self, throws: list[Throw]) -> NoReturn:
        exception_noun = pluralize(len(throws), "Exception")
        others_msg = f"\n(and {len(throws) - 1} more)\n" if len(throws) > 1 else ""
        raise ExecutionError(
            f"{exception_noun} encountered:\n\n"
            f"{throws[0].render(self._scheduler.include_trace_on_error)}\n"
            f"{others_msg}",
            wrapped_exceptions=tuple(t.exc for t in throws),
        )

    def execute(self, execution_request: ExecutionRequest) -> list[Any]:
        """Invoke the engine for the given ExecutionRequest, returning successful values or raising.

        :return: A sequence of per-request results.
        """
        returns, throws = self._execute(execution_request)

        # Throw handling.
        if throws:
            self._raise_on_error([t for _, t in throws])

        # Everything is a Return: we rely on the fact that roots are ordered to preserve subject
        # order in output lists.
        return [ret.value for _, ret in returns]

    def run_goal_rule(
        self,
        product: type[Goal],
        subject: Params,
        *,
        poll: bool = False,
        poll_delay: float | None = None,
    ) -> int:
        """
        :param product: A Goal subtype.
        :param subject: subject for the request.
        :param poll: See self.execution_request.
        :param poll_delay: See self.execution_request.
        :returns: An exit_code for the given Goal.
        """
        if self._scheduler.visualize_to_dir is not None:
            rule_graph_name = f"rule_graph.{product.name}.dot"
            params = self._scheduler._to_params_list(subject)
            self._scheduler.visualize_rule_subgraph_to_file(
                os.path.join(self._scheduler.visualize_to_dir, rule_graph_name),
                [type(p) for p in params],
                product,
            )
        with self._goals._execute(product):
            (return_value,) = self.product_request(
                product, [subject], poll=poll, poll_delay=poll_delay
            )
        return cast(int, return_value.exit_code)

    def product_request(
        self,
        product: type,
        subjects: Sequence[Any | Params],
        *,
        poll: bool = False,
        poll_delay: float | None = None,
        timeout: float | None = None,
    ) -> list:
        """Executes a request for a single product for some subjects, and returns the products.

        :param product: A product type for the request.
        :param subjects: A list of subjects or Params instances for the request.
        :param poll: See self.execution_request.
        :param poll_delay: See self.execution_request.
        :param timeout: See self.execution_request.
        :returns: A list of the requested products, with length match len(subjects).
        """
        request = self.execution_request(
            [(product, subject) for subject in subjects],
            poll=poll,
            poll_delay=poll_delay,
            timeout=timeout,
        )
        return self.execute(request)

    def capture_snapshots(self, path_globs_and_roots: Iterable[PathGlobsAndRoot]) -> list[Snapshot]:
        """Synchronously captures Snapshots for each matching PathGlobs rooted at a its root
        directory.

        This is a blocking operation, and should be avoided where possible.
        """
        return native_engine.capture_snapshots(
            self.py_scheduler,
            self.py_session,
            _PathGlobsAndRootCollection(path_globs_and_roots),
        )

    def single_file_digests_to_bytes(self, digests: Sequence[FileDigest]) -> list[bytes]:
        return native_engine.single_file_digests_to_bytes(self.py_scheduler, list(digests))

    def snapshots_to_file_contents(
        self, snapshots: Sequence[Snapshot]
    ) -> tuple[DigestContents, ...]:
        """For each input `Snapshot`, yield a single `DigestContents` containing all the
        `FileContent`s corresponding to the file(s) contained within that `Snapshot`.

        Note that we cannot currently use a parallelized version of `self.product_request` since
        each snapshot needs to yield a separate `DigestContents`.
        """
        return tuple(
            self.product_request(DigestContents, [snapshot.digest])[0] for snapshot in snapshots
        )

    def ensure_remote_has_recursive(self, digests: Sequence[Digest | FileDigest]) -> None:
        native_engine.ensure_remote_has_recursive(self.py_scheduler, list(digests))

    def ensure_directory_digest_persisted(self, digest: Digest) -> None:
        native_engine.ensure_directory_digest_persisted(self.py_scheduler, digest)

    def write_digest(
        self, digest: Digest, *, path_prefix: str | None = None, clear_paths: Sequence[str] = ()
    ) -> None:
        """Write a digest to disk, relative to the build root."""
        if path_prefix and PurePath(path_prefix).is_absolute():
            raise ValueError(
                f"The `path_prefix` {path_prefix} must be a relative path, as the engine writes "
                "the digest relative to the build root."
            )
        native_engine.write_digest(
            self.py_scheduler, self.py_session, digest, path_prefix or "", clear_paths
        )

    def lease_files_in_graph(self) -> None:
        native_engine.lease_files_in_graph(self.py_scheduler, self.py_session)

    def garbage_collect_store(self, target_size_bytes: int) -> None:
        self._scheduler.garbage_collect_store(target_size_bytes)

    def get_metrics(self) -> dict[str, int]:
        return native_engine.session_get_metrics(self.py_session)

    def get_observation_histograms(self) -> dict[str, Any]:
        return native_engine.session_get_observation_histograms(self.py_scheduler, self.py_session)

    def record_test_observation(self, value: int) -> None:
        native_engine.session_record_test_observation(self.py_scheduler, self.py_session, value)

    @property
    def is_cancelled(self) -> bool:
        return self.py_session.is_cancelled()

    def cancel(self) -> None:
        self.py_session.cancel()

    def wait_for_tail_tasks(self, timeout: float) -> None:
        native_engine.session_wait_for_tail_tasks(self.py_scheduler, self.py_session, timeout)


def register_rules(rule_index: RuleIndex, union_membership: UnionMembership) -> PyTasks:
    """Create a native Tasks object loaded with given RuleIndex."""
    tasks = PyTasks()

    def register_task(rule: TaskRule) -> None:
        native_engine.tasks_task_begin(
            tasks,
            rule.func,
            rule.output_type,
            tuple(rule.parameters.items()),
            rule.masked_types,
            side_effecting=any(issubclass(t, SideEffecting) for t in rule.parameters.values()),
            engine_aware_return_type=issubclass(rule.output_type, EngineAwareReturnType),
            cacheable=rule.cacheable,
            name=rule.canonical_name,
            desc=rule.desc or "",
            level=rule.level.level,
        )

        for awaitable in rule.awaitables:
            unions = [t for t in awaitable.input_types if is_union(t)]
            if len(unions) == 1:
                # Register the union by recording a copy of the Get for each union member.
                union = unions[0]
                in_scope_types = union_in_scope_types(union)
                assert in_scope_types is not None
                for union_member in union_membership.get(union):
                    native_engine.tasks_add_get_union(
                        tasks,
                        awaitable.output_type,
                        tuple(union_member if t == union else t for t in awaitable.input_types),
                        in_scope_types,
                    )
            elif len(unions) > 1:
                raise TypeError(
                    "Only one @union may be used in a Get, but {awaitable} used: {unions}."
                )
            elif awaitable.rule_id is not None:
                # Is a call to a known rule.
                native_engine.tasks_add_call(
                    tasks,
                    awaitable.output_type,
                    awaitable.input_types,
                    awaitable.rule_id,
                    awaitable.explicit_args_arity,
                )
            else:
                # Otherwise, the Get subject is a "concrete" type, so add a single Get edge.
                native_engine.tasks_add_get(tasks, awaitable.output_type, awaitable.input_types)

        native_engine.tasks_task_end(tasks)

    for task_rule in rule_index.rules:
        register_task(task_rule)
    for query in rule_index.queries:
        native_engine.tasks_add_query(
            tasks,
            query.output_type,
            query.input_types,
        )
    return tasks
