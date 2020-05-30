# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass
from textwrap import dedent
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    NoReturn,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    cast,
)

from typing_extensions import TypedDict

from pants.base.exception_sink import ExceptionSink
from pants.engine.collection import Collection
from pants.engine.fs import (
    Digest,
    DirectoryToMaterialize,
    MaterializeDirectoriesResult,
    MaterializeDirectoryResult,
    PathGlobsAndRoot,
)
from pants.engine.internals.native import Function, RawFdRunner, TypeId
from pants.engine.internals.nodes import Return, Throw
from pants.engine.rules import Rule, RuleIndex, TaskRule
from pants.engine.selectors import Params
from pants.engine.unions import union
from pants.option.global_options import ExecutionOptions
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import check_no_overlapping_paths
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

if TYPE_CHECKING:
    from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveProcessResult
    from pants.util.ordered_set import OrderedSet  # noqa


logger = logging.getLogger(__name__)


Workunit = Dict[str, Any]


class PolledWorkunits(TypedDict):
    started: Tuple[Workunit, ...]
    completed: Tuple[Workunit, ...]


@dataclass(frozen=True)
class ExecutionRequest:
    """Holds the roots for an execution, which might have been requested by a user.

    To create an ExecutionRequest, see `SchedulerSession.execution_request`.

    :param roots: Roots for this request.
    :type roots: list of tuples of subject and product.
    """

    roots: Any
    native: Any


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
        native,
        ignore_patterns: List[str],
        use_gitignore: bool,
        build_root: str,
        local_store_dir: str,
        local_execution_root_dir: str,
        named_caches_dir: str,
        rules: Tuple[Rule, ...],
        union_rules: Dict[Type, "OrderedSet[Type]"],
        execution_options: ExecutionOptions,
        include_trace_on_error: bool = True,
        visualize_to_dir: Optional[str] = None,
        validate: bool = True,
    ) -> None:
        """
        :param native: An instance of engine.native.Native.
        :param ignore_patterns: A list of gitignore-style file patterns for pants to ignore.
        :param use_gitignore: If set, pay attention to .gitignore files.
        :param build_root: The build root as a string.
        :param work_dir: The pants work dir.
        :param local_store_dir: The directory to use for storing the engine's LMDB store in.
        :param local_execution_root_dir: The directory to use for local execution sandboxes.
        :param named_caches_dir: The directory to use as the root for named mutable caches.
        :param rules: A set of Rules which is used to compute values in the graph.
        :param union_rules: A dict mapping union base types to member types so that rules can be written
                            against abstract union types without knowledge of downstream rulesets.
        :param execution_options: Execution options for (remote) processes.
        :param include_trace_on_error: Include the trace through the graph upon encountering errors.
        :type include_trace_on_error: bool
        :param validate: True to assert that the ruleset is valid.
        """
        self._native = native
        self.include_trace_on_error = include_trace_on_error
        self._visualize_to_dir = visualize_to_dir
        # Validate and register all provided and intrinsic tasks.
        rule_index = RuleIndex.create(list(rules), union_rules)
        self._root_subject_types = [r.output_type for r in rule_index.roots]

        # Create the native Scheduler and Session.
        tasks = self._register_rules(rule_index)

        self._scheduler = native.new_scheduler(
            tasks=tasks,
            root_subject_types=self._root_subject_types,
            build_root=build_root,
            local_store_dir=local_store_dir,
            local_execution_root_dir=local_execution_root_dir,
            named_caches_dir=named_caches_dir,
            ignore_patterns=ignore_patterns,
            use_gitignore=use_gitignore,
            execution_options=execution_options,
        )

        # If configured, visualize the rule graph before asserting that it is valid.
        if self._visualize_to_dir is not None:
            rule_graph_name = "rule_graph.dot"
            self.visualize_rule_graph_to_file(os.path.join(self._visualize_to_dir, rule_graph_name))

        if validate:
            self._assert_ruleset_valid()

    def graph_trace(self, session, execution_request):
        with temporary_file_path() as path:
            self._native.lib.graph_trace(self._scheduler, session, execution_request, path.encode())
            with open(path, "r") as fd:
                for line in fd.readlines():
                    yield line.rstrip()

    def _assert_ruleset_valid(self):
        self._raise_or_return(self._native.lib.validator_run(self._scheduler))

    def _to_vals_buf(self, objs):
        return self._native.context.vals_buf(
            tuple(self._native.context.to_value(obj) for obj in objs)
        )

    def _to_value(self, obj):
        return self._native.context.to_value(obj)

    def _from_value(self, val):
        return self._native.context.from_value(val)

    def _raise_or_return(self, pyresult):
        return self._native.context.raise_or_return(pyresult)

    def _to_id(self, typ):
        return self._native.context.to_id(typ)

    def _to_key(self, obj):
        return self._native.context.to_key(obj)

    def _from_key(self, cdata):
        return self._native.context.from_key(cdata)

    def _to_type(self, type_obj):
        return TypeId(self._to_id(type_obj))

    def _to_ids_buf(self, types):
        return self._native.to_ids_buf(types)

    def _to_utf8_buf(self, string):
        return self._native.context.utf8_buf(string)

    def _to_params_list(self, subject_or_params):
        if isinstance(subject_or_params, Params):
            return subject_or_params.params
        return [subject_or_params]

    def _register_rules(self, rule_index: RuleIndex):
        """Create a native Tasks object, and record the given RuleIndex on it."""

        tasks = self._native.new_tasks()

        for output_type, rules in rule_index.rules.items():
            for rule in rules:
                if type(rule) is TaskRule:
                    self._register_task(tasks, output_type, rule, rule_index.union_rules)
                else:
                    raise ValueError("Unexpected Rule type: {}".format(rule))
        return tasks

    def _register_task(
        self, tasks, output_type, rule: TaskRule, union_rules: Dict[Type, "OrderedSet[Type]"]
    ) -> None:
        """Register the given TaskRule with the native scheduler."""
        func = Function(self._to_key(rule.func))
        self._native.lib.tasks_task_begin(tasks, func, self._to_type(output_type), rule.cacheable)
        for selector in rule.input_selectors:
            self._native.lib.tasks_add_select(tasks, self._to_type(selector))

        anno = rule.annotations
        if anno.canonical_name:
            name = anno.canonical_name
            desc = anno.desc if anno.desc else ""
            self._native.lib.tasks_add_display_info(tasks, name.encode(), desc.encode())

        def add_get_edge(product, subject):
            self._native.lib.tasks_add_get(tasks, self._to_type(product), self._to_type(subject))

        for the_get in rule.input_gets:
            if union.is_instance(the_get.subject_declared_type):
                # If the registered subject type is a union, add Get edges to all registered union members.
                for union_member in union_rules.get(the_get.subject_declared_type, []):
                    add_get_edge(the_get.product_type, union_member)
            else:
                # Otherwise, the Get subject is a "concrete" type, so add a single Get edge.
                add_get_edge(the_get.product_type, the_get.subject_declared_type)

        self._native.lib.tasks_task_end(tasks)

    def visualize_graph_to_file(self, session, filename):
        res = self._native.lib.graph_visualize(self._scheduler, session, filename.encode())
        self._raise_or_return(res)

    def visualize_rule_graph_to_file(self, filename):
        res = self._native.lib.rule_graph_visualize(self._scheduler, filename.encode())
        self._raise_or_return(res)

    def visualize_rule_subgraph_to_file(self, filename, root_subject_types, product_type):
        root_type_ids = self._to_ids_buf(root_subject_types)
        product_type_id = TypeId(self._to_id(product_type))
        res = self._native.lib.rule_subgraph_visualize(
            self._scheduler, root_type_ids, product_type_id, filename.encode()
        )
        self._raise_or_return(res)

    def rule_graph_visualization(self):
        with temporary_file_path() as path:
            self.visualize_rule_graph_to_file(path)
            with open(path) as fd:
                for line in fd.readlines():
                    yield line.rstrip()

    def rule_subgraph_visualization(self, root_subject_types, product_type):
        with temporary_file_path() as path:
            self.visualize_rule_subgraph_to_file(path, root_subject_types, product_type)
            with open(path, "r") as fd:
                for line in fd.readlines():
                    yield line.rstrip()

    def invalidate_files(self, direct_filenames):
        # NB: Watchman no longer triggers events when children are created/deleted under a directory,
        # so we always need to invalidate the direct parent as well.
        filenames = set(direct_filenames)
        filenames.update(os.path.dirname(f) for f in direct_filenames)
        filenames_buf = self._native.context.utf8_buf_buf(filenames)
        return self._native.lib.graph_invalidate(self._scheduler, filenames_buf)

    def invalidate_all_files(self):
        return self._native.lib.graph_invalidate_all_paths(self._scheduler)

    def check_invalidation_watcher_liveness(self):
        res = self._native.lib.check_invalidation_watcher_liveness(self._scheduler)
        self._raise_or_return(res)

    def graph_len(self):
        return self._native.lib.graph_len(self._scheduler)

    def execution_add_root_select(self, execution_request, subject_or_params, product):
        params = self._to_params_list(subject_or_params)
        res = self._native.lib.execution_add_root_select(
            self._scheduler, execution_request, self._to_vals_buf(params), self._to_type(product)
        )
        self._raise_or_return(res)

    def execution_set_timeout(self, execution_request, timeout: float):
        timeout_in_ms = int(timeout * 1000)
        self._native.lib.execution_set_timeout(execution_request, timeout_in_ms)

    def execution_set_poll(self, execution_request, poll: bool):
        self._native.lib.execution_set_poll(execution_request, poll)

    def execution_set_poll_delay(self, execution_request, poll_delay: float):
        poll_delay_in_ms = int(poll_delay * 1000)
        self._native.lib.execution_set_poll_delay(execution_request, poll_delay_in_ms)

    @property
    def visualize_to_dir(self):
        return self._visualize_to_dir

    def _metrics(self, session):
        return self._from_value(self._native.lib.scheduler_metrics(self._scheduler, session))

    def poll_workunits(self, session, max_log_verbosity: LogLevel) -> PolledWorkunits:
        max_verbosity = max_log_verbosity.level
        result: Tuple[Tuple[Workunit], Tuple[Workunit]] = self._from_value(
            self._native.lib.poll_session_workunits(self._scheduler, session, max_verbosity)
        )
        return {"started": result[0], "completed": result[1]}

    def _run_and_return_roots(self, session, execution_request):
        raw_roots = self._native.lib.scheduler_execute(self._scheduler, session, execution_request)
        if raw_roots.err == self._native.lib.NoError:
            pass
        elif raw_roots.err == self._native.lib.KeyboardInterrupt:
            raise KeyboardInterrupt
        elif raw_roots.err == self._native.lib.Timeout:
            raise ExecutionTimeoutError("Timed out")
        else:
            raise Exception(f"Unrecognized error type from native execution: {raw_roots.err}")

        remaining_runtime_exceptions_to_capture = list(
            self._native.consume_cffi_extern_method_runtime_exceptions()
        )
        try:
            roots = []
            for raw_root in self._native.unpack(raw_roots.nodes_ptr, raw_roots.nodes_len):
                # Check if there were any uncaught exceptions within rules that were executed.
                remaining_runtime_exceptions_to_capture.extend(
                    self._native.consume_cffi_extern_method_runtime_exceptions()
                )

                if raw_root.is_throw:
                    state = Throw(
                        self._from_value(raw_root.result),
                        python_traceback=self._from_value(raw_root.python_traceback),
                        engine_traceback=self._from_value(raw_root.engine_traceback),
                    )
                elif raw_root.result == self._native.ffi.NULL:
                    # NB: We expect all NULL handles to correspond to uncaught exceptions which are collected
                    # in `self._native._peek_cffi_extern_method_runtime_exceptions()`!
                    if not remaining_runtime_exceptions_to_capture:
                        raise ExecutionError(
                            "Internal logic error in scheduler: expected more elements in "
                            "`self._native._peek_cffi_extern_method_runtime_exceptions()`."
                        )
                    matching_runtime_exception = remaining_runtime_exceptions_to_capture.pop(0)
                    state = Throw(matching_runtime_exception)
                else:
                    state = Return(self._from_value(raw_root.result))
                roots.append(state)
        finally:
            self._native.lib.nodes_destroy(raw_roots)

        if remaining_runtime_exceptions_to_capture:
            raise ExecutionError(
                "Internal logic error in scheduler: expected elements in "
                "`self._native._peek_cffi_extern_method_runtime_exceptions()`."
            )
        return roots

    def lease_files_in_graph(self, session):
        self._native.lib.lease_files_in_graph(self._scheduler, session)

    def garbage_collect_store(self):
        self._native.lib.garbage_collect_store(self._scheduler)

    def nailgun_server_await_bound(self, nailgun_server) -> int:
        """Blocks until the server has bound a port, and then returns the port.

        Returns the actual port the server has successfully bound to, or raises an exception if the
        server has exited.
        """
        return cast(int, self._native.nailgun_server_await_bound(self._scheduler, nailgun_server))

    def new_nailgun_server(self, port_requested: int, runner: RawFdRunner):
        """Creates a nailgun server with a requested port.

        Returns the server and the actual port it bound to.
        """
        return self._native.new_nailgun_server(self._scheduler, port_requested, runner)

    def new_session(
        self,
        zipkin_trace_v2: bool,
        build_id,
        dynamic_ui: bool = False,
        should_report_workunits: bool = False,
    ) -> "SchedulerSession":
        """Creates a new SchedulerSession for this Scheduler."""
        return SchedulerSession(
            self,
            self._native.new_session(
                self._scheduler, zipkin_trace_v2, dynamic_ui, build_id, should_report_workunits,
            ),
        )


class _PathGlobsAndRootCollection(Collection[PathGlobsAndRoot]):
    pass


class _DirectoryDigests(Collection[Digest]):
    pass


class _DirectoriesToMaterialize(Collection[DirectoryToMaterialize]):
    pass


class SchedulerSession:
    """A handle to a shared underlying Scheduler and a unique Session.

    Generally a Session corresponds to a single run of pants: some metrics are specific to a
    Session.
    """

    def __init__(self, scheduler, session):
        self._scheduler = scheduler
        self._session = session
        self._run_count = 0

    @property
    def scheduler(self):
        return self._scheduler

    @property
    def session(self):
        return self._session

    def poll_workunits(self, max_log_verbosity: LogLevel) -> PolledWorkunits:
        return cast(
            PolledWorkunits, self._scheduler.poll_workunits(self._session, max_log_verbosity)
        )

    def graph_len(self):
        return self._scheduler.graph_len()

    def new_run_id(self):
        """Assigns a new "run id" to this Session, without creating a new Session.

        Usually each Session corresponds to one end user "run", but there are exceptions: notably,
        the `--loop` feature uses one Session, but would like to observe new values for uncacheable
        nodes in each iteration of its loop.
        """
        self._scheduler._native.lib.session_new_run_id(self._session)

    def visualize_graph_to_file(self, filename):
        """Visualize a graph walk by writing graphviz `dot` output to a file.

        :param str filename: The filename to output the graphviz output to.
        """
        self._scheduler.visualize_graph_to_file(self._session, filename)

    def visualize_rule_graph_to_file(self, filename):
        self._scheduler.visualize_rule_graph_to_file(filename)

    def execution_request(
        self,
        products: Sequence[Type],
        subjects: Sequence[Union[Any, Params]],
        poll: bool = False,
        poll_delay: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> ExecutionRequest:
        """Create and return an ExecutionRequest for the given products and subjects.

        The resulting ExecutionRequest object will contain keys tied to this scheduler's product Graph,
        and so it will not be directly usable with other scheduler instances without being re-created.

        NB: This method does a "cross product", mapping all subjects to all products.

        :param products: A list of product types to request for the roots.
        :param subjects: A list of singleton input parameters or Params instances.
        :param poll: True to wait for _all_ of the given roots to
          have changed since their last observed values in this SchedulerSession.
        :param poll_delay: A delay (in seconds) to wait after observing a change, and before
          beginning to compute a new value.
        :param timeout: An optional timeout to wait for the request to complete (in seconds). If the
          request has not completed before the timeout has elapsed, ExecutionTimeoutError is raised.
        :returns: An ExecutionRequest for the given products and subjects.
        """
        request_specs = tuple((s, p) for s in subjects for p in products)
        native_execution_request = self._scheduler._native.new_execution_request()
        for subject, product in request_specs:
            self._scheduler.execution_add_root_select(native_execution_request, subject, product)
        if timeout:
            self._scheduler.execution_set_timeout(native_execution_request, timeout)
        if poll_delay:
            self._scheduler.execution_set_poll_delay(native_execution_request, poll_delay)
        self._scheduler.execution_set_poll(native_execution_request, poll)
        return ExecutionRequest(request_specs, native_execution_request)

    def invalidate_files(self, direct_filenames):
        """Invalidates the given filenames in an internal product Graph instance."""
        invalidated = self._scheduler.invalidate_files(direct_filenames)
        self._maybe_visualize()
        return invalidated

    def invalidate_all_files(self):
        """Invalidates all filenames in an internal product Graph instance."""
        invalidated = self._scheduler.invalidate_all_files()
        self._maybe_visualize()
        return invalidated

    def node_count(self):
        return self._scheduler.graph_len()

    def metrics(self):
        """Returns metrics for this SchedulerSession as a dict of metric name to metric value."""
        return self._scheduler._metrics(self._session)

    @staticmethod
    def engine_workunits(metrics):
        return metrics.get("engine_workunits")

    def _maybe_visualize(self):
        if self._scheduler.visualize_to_dir is not None:
            name = f"graph.{self._run_count:03d}.dot"
            self._run_count += 1
            self.visualize_graph_to_file(os.path.join(self._scheduler.visualize_to_dir, name))

    def execute(self, execution_request: ExecutionRequest):
        """Invoke the engine for the given ExecutionRequest, returning Return and Throw states.

        :return: A tuple of (root, Return) tuples and (root, Throw) tuples.
        """
        start_time = time.time()
        roots = list(
            zip(
                execution_request.roots,
                self._scheduler._run_and_return_roots(self._session, execution_request.native),
            ),
        )

        ExceptionSink.toggle_ignoring_sigint_v2_engine(False)

        self._maybe_visualize()

        logger.debug(
            "computed %s nodes in %f seconds. there are %s total nodes.",
            len(roots),
            time.time() - start_time,
            self._scheduler.graph_len(),
        )

        returns = tuple((root, state) for root, state in roots if type(state) is Return)
        throws = tuple((root, state) for root, state in roots if type(state) is Throw)
        return cast(Tuple[Tuple[Return, ...], Tuple[Throw, ...]], (returns, throws))

    def _raise_on_error(self, throws: List[Throw]) -> NoReturn:
        exception_noun = pluralize(len(throws), "Exception")

        if self._scheduler.include_trace_on_error:
            throw = throws[0]
            etb = throw.engine_traceback
            python_traceback_str = throw.python_traceback or ""
            engine_traceback_str = ""
            others_msg = f"\n(and {len(throws) - 1} more)" if len(throws) > 1 else ""
            if etb:
                sep = "\n  in "
                engine_traceback_str = "Engine traceback:" + sep + sep.join(reversed(etb)) + "\n"
            raise ExecutionError(
                f"{exception_noun} encountered:\n\n"
                f"{engine_traceback_str}"
                f"{python_traceback_str}"
                f"{others_msg}",
                wrapped_exceptions=tuple(t.exc for t in throws),
            )
        else:
            exception_strs = "\n  ".join(f"{type(t.exc).__name__}: {str(t.exc)}" for t in throws)
            raise ExecutionError(
                f"{exception_noun} encountered:\n\n" f"  {exception_strs}\n",
                wrapped_exceptions=tuple(t.exc for t in throws),
            )

    def run_goal_rule(
        self,
        product: Type,
        subject: Union[Any, Params],
        poll: bool = False,
        poll_delay: Optional[float] = None,
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

        request = self.execution_request([product], [subject], poll=poll, poll_delay=poll_delay)
        returns, throws = self.execute(request)

        if throws:
            self._raise_on_error([t for _, t in throws])
        _, state = returns[0]
        return cast(int, state.value.exit_code)

    def product_request(
        self,
        product: Type,
        subjects: Sequence[Union[Any, Params]],
        poll: bool = False,
        timeout: Optional[float] = None,
    ):
        """Executes a request for a single product for some subjects, and returns the products.

        :param product: A product type for the request.
        :param subjects: A list of subjects or Params instances for the request.
        :param poll: See self.execution_request.
        :param timeout: See self.execution_request.
        :returns: A list of the requested products, with length match len(subjects).
        """
        request = None
        raised_exception = None
        try:
            request = self.execution_request([product], subjects, poll=poll, timeout=timeout)
        except Exception:
            # If there are any exceptions during CFFI extern method calls, we want to return an error with
            # them and whatever failure results from it. This typically results from unhashable types.
            if self._scheduler._native._peek_cffi_extern_method_runtime_exceptions():
                raised_exception = sys.exc_info()[0:3]
            else:
                # Otherwise, this is likely an exception coming from somewhere else, and we don't want to
                # swallow that, so re-raise.
                raise

        # We still want to raise whenever there are any exceptions in any CFFI extern methods, even if
        # that didn't lead to an exception in generating the execution request for some reason, so we
        # check the extern exceptions list again.
        internal_errors = self._scheduler._native.consume_cffi_extern_method_runtime_exceptions()
        if internal_errors:
            error_tracebacks = [
                "".join(
                    traceback.format_exception(
                        etype=error_info.exc_type,
                        value=error_info.exc_value,
                        tb=error_info.traceback,
                    )
                )
                for error_info in internal_errors
            ]

            raised_exception_message = None
            if raised_exception:
                exc_type, exc_value, tb = raised_exception
                raised_exception_message = dedent(
                    """\
                    The engine execution request raised this error, which is probably due to the errors in the
                    CFFI extern methods listed above, as CFFI externs return None upon error:
                    {}
                    """
                ).format(
                    "".join(traceback.format_exception(etype=exc_type, value=exc_value, tb=tb))
                )

            raise ExecutionError(
                dedent(
                    """\
                    {error_description} raised in CFFI extern methods:
                    {joined_tracebacks}{raised_exception_message}
                    """
                ).format(
                    error_description=pluralize(len(internal_errors), "Exception"),
                    joined_tracebacks="\n+++++++++\n".join(
                        formatted_tb for formatted_tb in error_tracebacks
                    ),
                    raised_exception_message=(
                        "\n\n{}".format(raised_exception_message)
                        if raised_exception_message
                        else ""
                    ),
                )
            )

        returns, throws = self.execute(cast(ExecutionRequest, request))

        # Throw handling.
        if throws:
            self._raise_on_error([t for _, t in throws])

        # Everything is a Return: we rely on the fact that roots are ordered to preserve subject
        # order in output lists.
        return [ret.value for _, ret in returns]

    def capture_snapshots(self, path_globs_and_roots):
        """Synchronously captures Snapshots for each matching PathGlobs rooted at a its root
        directory.

        This is a blocking operation, and should be avoided where possible.

        :param path_globs_and_roots tuple<PathGlobsAndRoot>: The PathGlobs to capture, and the root
               directory relative to which each should be captured.
        :returns: A tuple of Snapshots.
        """
        result = self._scheduler._native.lib.capture_snapshots(
            self._scheduler._scheduler,
            self._session,
            self._scheduler._to_value(_PathGlobsAndRootCollection(path_globs_and_roots)),
        )
        return self._scheduler._raise_or_return(result)

    def merge_directories(self, digests):
        """Merges any number of directories.

        :param digests: Tuple of directory digests.
        :return: A Digest.
        """
        result = self._scheduler._native.lib.merge_directories(
            self._scheduler._scheduler,
            self._session,
            self._scheduler._to_value(_DirectoryDigests(digests)),
        )
        return self._scheduler._raise_or_return(result)

    def run_local_interactive_process(
        self, request: "InteractiveProcessRequest"
    ) -> "InteractiveProcessResult":
        sched_pointer = self._scheduler._scheduler
        session_pointer = self._session

        wrapped_result = self._scheduler._native.lib.run_local_interactive_process(
            sched_pointer, session_pointer, self._scheduler._to_value(request)
        )
        result: "InteractiveProcessResult" = self._scheduler._raise_or_return(wrapped_result)
        return result

    def materialize_directory(
        self, directory_to_materialize: DirectoryToMaterialize
    ) -> MaterializeDirectoryResult:
        """Materialize one single directory digest to disk.

        If you need to materialize multiple, you should use the parallel materialize_directories()
        instead.
        """
        return self.materialize_directories((directory_to_materialize,)).dependencies[0]

    def materialize_directories(
        self, directories_to_materialize: Tuple[DirectoryToMaterialize, ...]
    ) -> MaterializeDirectoriesResult:
        """Materialize multiple directory digests to disk in parallel."""
        # Ensure that there isn't more than one of the same directory paths and paths do not have the
        # same prefix.
        dir_list = [dtm.path_prefix for dtm in directories_to_materialize]
        check_no_overlapping_paths(dir_list)

        wrapped_result = self._scheduler._native.lib.materialize_directories(
            self._scheduler._scheduler,
            self._session,
            self._scheduler._to_value(_DirectoriesToMaterialize(directories_to_materialize)),
        )
        result: MaterializeDirectoriesResult = self._scheduler._raise_or_return(wrapped_result)
        return result

    def lease_files_in_graph(self):
        self._scheduler.lease_files_in_graph(self._session)

    def garbage_collect_store(self):
        self._scheduler.garbage_collect_store()
