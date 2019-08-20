# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import multiprocessing
import os
import sys
import time
import traceback
from textwrap import dedent
from types import GeneratorType

from pants.base.exiter import PANTS_FAILED_EXIT_CODE
from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.fs import (Digest, DirectoriesToMerge, DirectoryToMaterialize,
                             DirectoryWithPrefixToStrip, FileContent, FilesContent, PathGlobs,
                             PathGlobsAndRoot, Snapshot, UrlToFetch)
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.native import Function, TypeId
from pants.engine.nodes import Return, Throw
from pants.engine.objects import Collection
from pants.engine.rules import RuleIndex, TaskRule
from pants.engine.selectors import Params
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import check_no_overlapping_paths
from pants.util.objects import datatype
from pants.util.strutil import pluralize


logger = logging.getLogger(__name__)


class ExecutionRequest(datatype(['roots', 'native'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `SchedulerSession.execution_request`.

  :param roots: Roots for this request.
  :type roots: list of tuples of subject and product.
  """


class ExecutionError(Exception):
  def __init__(self, message, wrapped_exceptions=None):
    super().__init__(message)
    self.wrapped_exceptions = wrapped_exceptions or ()


class Scheduler:
  def __init__(
    self,
    native,
    project_tree,
    local_store_dir,
    rules,
    union_rules,
    execution_options,
    include_trace_on_error=True,
    validate=True,
    visualize_to_dir=None,
  ):
    """
    :param native: An instance of engine.native.Native.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param work_dir: The pants work dir.
    :param local_store_dir: The directory to use for storing the engine's LMDB store in.
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
    # TODO: This `_tasks` reference could be a local variable, since it is not used
    # after construction.
    self._tasks = native.new_tasks()
    self._register_rules(rule_index)

    self._scheduler = native.new_scheduler(
      tasks=self._tasks,
      root_subject_types=self._root_subject_types,
      build_root=project_tree.build_root,
      local_store_dir=local_store_dir,
      ignore_patterns=project_tree.ignore_patterns,
      execution_options=execution_options,
      construct_directory_digest=Digest,
      construct_snapshot=Snapshot,
      construct_file_content=FileContent,
      construct_files_content=FilesContent,
      construct_process_result=FallibleExecuteProcessResult,
      type_address=Address,
      type_path_globs=PathGlobs,
      type_directory_digest=Digest,
      type_snapshot=Snapshot,
      type_merge_snapshots_request=DirectoriesToMerge,
      type_directory_with_prefix_to_strip=DirectoryWithPrefixToStrip,
      type_files_content=FilesContent,
      type_dir=Dir,
      type_file=File,
      type_link=Link,
      type_process_request=ExecuteProcessRequest,
      type_process_result=FallibleExecuteProcessResult,
      type_generator=GeneratorType,
      type_url_to_fetch=UrlToFetch,
    )


    # If configured, visualize the rule graph before asserting that it is valid.
    if self._visualize_to_dir is not None:
      rule_graph_name = 'rule_graph.dot'
      self.visualize_rule_graph_to_file(os.path.join(self._visualize_to_dir, rule_graph_name))

    if validate:
      self._assert_ruleset_valid()

  def _root_type_ids(self):
    return self._to_ids_buf(self._root_subject_types)

  def graph_trace(self, execution_request):
    with temporary_file_path() as path:
      self._native.lib.graph_trace(self._scheduler, execution_request, path.encode())
      with open(path, 'r') as fd:
        for line in fd.readlines():
          yield line.rstrip()

  def _assert_ruleset_valid(self):
    self._raise_or_return(self._native.lib.validator_run(self._scheduler))

  def _to_vals_buf(self, objs):
    return self._native.context.vals_buf(tuple(self._native.context.to_value(obj) for obj in objs))

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

  def _register_rules(self, rule_index):
    """Record the given RuleIndex on `self._tasks`."""
    registered = set()
    for output_type, rules in rule_index.rules.items():
      for rule in rules:
        key = (output_type, rule)
        if key in registered:
          continue
        registered.add(key)

        if type(rule) is TaskRule:
          self._register_task(output_type, rule, rule_index.union_rules)
        else:
          raise ValueError('Unexpected Rule type: {}'.format(rule))

  def _register_task(self, output_type, rule, union_rules):
    """Register the given TaskRule with the native scheduler."""
    func = Function(self._to_key(rule.func))
    self._native.lib.tasks_task_begin(self._tasks, func, self._to_type(output_type), rule.cacheable)
    for selector in rule.input_selectors:
      self._native.lib.tasks_add_select(self._tasks, self._to_type(selector))

    def add_get_edge(product, subject):
      self._native.lib.tasks_add_get(self._tasks, self._to_type(product), self._to_type(subject))

    for the_get in rule.input_gets:
      if getattr(the_get.subject_declared_type, '_is_union', False):
        # If the registered subject type is a union, add Get edges to all registered union members.
        for union_member in union_rules.get(the_get.subject_declared_type, []):
          add_get_edge(the_get.product, union_member)
      else:
        # Otherwise, the Get subject is a "concrete" type, so add a single Get edge.
        add_get_edge(the_get.product, the_get.subject_declared_type)

    self._native.lib.tasks_task_end(self._tasks)

  def visualize_graph_to_file(self, session, filename):
    res = self._native.lib.graph_visualize(self._scheduler, session, filename.encode())
    self._raise_or_return(res)

  def visualize_rule_graph_to_file(self, filename):
    self._native.lib.rule_graph_visualize(
      self._scheduler,
      self._root_type_ids(),
      filename.encode())

  def rule_graph_visualization(self):
    with temporary_file_path() as path:
      self.visualize_rule_graph_to_file(path)
      with open(path) as fd:
        for line in fd.readlines():
          yield line.rstrip()

  def rule_subgraph_visualization(self, root_subject_type, product_type):
    root_type_id = TypeId(self._to_id(root_subject_type))

    product_type_id = TypeId(self._to_id(product_type))
    with temporary_file_path() as path:
      self._native.lib.rule_subgraph_visualize(
        self._scheduler,
        root_type_id,
        product_type_id,
        path.encode())
      with open(path, 'r') as fd:
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

  def graph_len(self):
    return self._native.lib.graph_len(self._scheduler)

  def add_root_selection(self, execution_request, subject_or_params, product):
    if isinstance(subject_or_params, Params):
      params = subject_or_params.params
    else:
      params = [subject_or_params]
    res = self._native.lib.execution_add_root_select(self._scheduler,
                                                     execution_request,
                                                     self._to_vals_buf(params),
                                                     self._to_type(product))
    self._raise_or_return(res)

  def visualize_to_dir(self):
    return self._visualize_to_dir

  def _metrics(self, session):
    return self._from_value(self._native.lib.scheduler_metrics(self._scheduler, session))

  def with_fork_context(self, func):
    """See the rustdocs for `scheduler_fork_context` for more information."""
    res = self._native.lib.scheduler_fork_context(self._scheduler, Function(self._to_key(func)))
    return self._raise_or_return(res)

  def _run_and_return_roots(self, session, execution_request):
    raw_roots = self._native.lib.scheduler_execute(self._scheduler, session, execution_request)
    try:
      roots = []
      for raw_root in self._native.unpack(raw_roots.nodes_ptr, raw_roots.nodes_len):
        if raw_root.is_throw:
          state = Throw(self._from_value(raw_root.handle))
        else:
          state = Return(self._from_value(raw_root.handle))
        roots.append(state)
    finally:
      self._native.lib.nodes_destroy(raw_roots)
    return roots

  def capture_snapshots(self, path_globs_and_roots):
    """Synchronously captures Snapshots for each matching PathGlobs rooted at a its root directory.

    This is a blocking operation, and should be avoided where possible.

    :param path_globs_and_roots tuple<PathGlobsAndRoot>: The PathGlobs to capture, and the root
           directory relative to which each should be captured.
    :returns: A tuple of Snapshots.
    """
    result = self._native.lib.capture_snapshots(
      self._scheduler,
      self._to_value(_PathGlobsAndRootCollection(path_globs_and_roots)),
    )
    return self._raise_or_return(result)

  def merge_directories(self, directory_digests):
    """Merges any number of directories.

    :param directory_digests: Tuple of DirectoryDigests.
    :return: A Digest.
    """
    result = self._native.lib.merge_directories(
      self._scheduler,
      self._to_value(_DirectoryDigests(directory_digests)),
    )
    return self._raise_or_return(result)

  def materialize_directories(self, directories_paths_and_digests):
    """Creates the specified directories on the file system.

    :param directories_paths_and_digests tuple<DirectoryToMaterialize>: Tuple of the path and
           digest of the directories to materialize.
    :returns: Nothing or an error.
    """
    # Ensure there isn't more than one of the same directory paths and paths do not have the same prefix.
    dir_list = [dpad.path for dpad in directories_paths_and_digests]
    check_no_overlapping_paths(dir_list)

    result = self._native.lib.materialize_directories(
      self._scheduler,
      self._to_value(_DirectoriesToMaterialize(directories_paths_and_digests)),
    )
    return self._raise_or_return(result)

  def lease_files_in_graph(self):
    self._native.lib.lease_files_in_graph(self._scheduler)

  def garbage_collect_store(self):
    self._native.lib.garbage_collect_store(self._scheduler)

  def new_session(self, zipkin_trace_v2, v2_ui=False):
    """Creates a new SchedulerSession for this Scheduler."""
    return SchedulerSession(self, self._native.new_session(
      self._scheduler, zipkin_trace_v2, v2_ui, multiprocessing.cpu_count())
    )


_PathGlobsAndRootCollection = Collection.of(PathGlobsAndRoot)


_DirectoryDigests = Collection.of(Digest)


_DirectoriesToMaterialize = Collection.of(DirectoryToMaterialize)


class SchedulerSession:
  """A handle to a shared underlying Scheduler and a unique Session.

  Generally a Session corresponds to a single run of pants: some metrics are specific to
  a Session.
  """

  execution_error_type = ExecutionError

  def __init__(self, scheduler, session):
    self._scheduler = scheduler
    self._session = session
    self._run_count = 0

  def graph_len(self):
    return self._scheduler.graph_len()

  def trace(self, execution_request):
    """Yields a stringified 'stacktrace' starting from the scheduler's roots."""
    for line in self._scheduler.graph_trace(execution_request.native):
      yield line

  def visualize_graph_to_file(self, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param str filename: The filename to output the graphviz output to.
    """
    self._scheduler.visualize_graph_to_file(self._session, filename)

  def visualize_rule_graph_to_file(self, filename):
    self._scheduler.visualize_rule_graph_to_file(filename)

  def execution_request_literal(self, request_specs):
    native_execution_request = self._scheduler._native.new_execution_request()
    for subject, product in request_specs:
      self._scheduler.add_root_selection(native_execution_request, subject, product)
    return ExecutionRequest(request_specs, native_execution_request)

  def execution_request(self, products, subjects):
    """Create and return an ExecutionRequest for the given products and subjects.

    The resulting ExecutionRequest object will contain keys tied to this scheduler's product Graph,
    and so it will not be directly usable with other scheduler instances without being re-created.

    NB: This method does a "cross product", mapping all subjects to all products. To create a
    request for just the given list of subject -> product tuples, use `execution_request_literal()`!

    :param products: A list of product types to request for the roots.
    :type products: list of types
    :param subjects: A list of Spec and/or PathGlobs objects.
    :type subject: list of :class:`pants.base.specs.Spec`, `pants.build_graph.Address`, and/or
      :class:`pants.engine.fs.PathGlobs` objects.
    :returns: An ExecutionRequest for the given products and subjects.
    """
    roots = (tuple((s, p) for s in subjects for p in products))
    return self.execution_request_literal(roots)

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

  def with_fork_context(self, func):
    return self._scheduler.with_fork_context(func)

  def _maybe_visualize(self):
    if self._scheduler.visualize_to_dir() is not None:
      name = 'graph.{0:03d}.dot'.format(self._run_count)
      self._run_count += 1
      self.visualize_graph_to_file(os.path.join(self._scheduler.visualize_to_dir(), name))

  def execute(self, execution_request):
    """Invoke the engine for the given ExecutionRequest, returning Return and Throw states.

    :return: A tuple of (root, Return) tuples and (root, Throw) tuples.
    """
    start_time = time.time()
    roots = list(zip(execution_request.roots,
                     self._scheduler._run_and_return_roots(self._session, execution_request.native)))

    self._maybe_visualize()

    logger.debug(
      'computed %s nodes in %f seconds. there are %s total nodes.',
      len(roots),
      time.time() - start_time,
      self._scheduler.graph_len()
    )

    returns = tuple((root, state) for root, state in roots if type(state) is Return)
    throws = tuple((root, state) for root, state in roots if type(state) is Throw)
    return returns, throws

  def _trace_on_error(self, unique_exceptions, request):
    exception_noun = pluralize(len(unique_exceptions), 'Exception')
    if self._scheduler.include_trace_on_error:
      cumulative_trace = '\n'.join(self.trace(request))
      raise ExecutionError(
        '{} encountered:\n{}'.format(exception_noun, cumulative_trace),
        unique_exceptions,
      )
    else:
      raise ExecutionError(
        '{} encountered:\n  {}'.format(
          exception_noun,
          '\n  '.join('{}: {}'.format(type(t).__name__, str(t)) for t in unique_exceptions)),
        unique_exceptions
      )

  def run_console_rule(self, product, subject):
    """
    :param product: A Goal subtype.
    :param subject: subject for the request.
    :returns: An exit_code for the given Goal.
    """
    request = self.execution_request([product], [subject])
    returns, throws = self.execute(request)

    if throws:
      _, state = throws[0]
      exc = state.exc
      self._trace_on_error([exc], request)
      return PANTS_FAILED_EXIT_CODE
    _, state = returns[0]
    return state.value.exit_code

  def product_request(self, product, subjects):
    """Executes a request for a single product for some subjects, and returns the products.

    :param class product: A product type for the request.
    :param list subjects: A list of subjects or Params instances for the request.
    :returns: A list of the requested products, with length match len(subjects).
    """
    request = None
    raised_exception = None
    try:
      request = self.execution_request([product], subjects)
    except:                     # noqa: T803
      # If there are any exceptions during CFFI extern method calls, we want to return an error with
      # them and whatever failure results from it. This typically results from unhashable types.
      if self._scheduler._native.cffi_extern_method_runtime_exceptions():
        raised_exception = sys.exc_info()[0:3]
      else:
        # Otherwise, this is likely an exception coming from somewhere else, and we don't want to
        # swallow that, so re-raise.
        raise

    # We still want to raise whenever there are any exceptions in any CFFI extern methods, even if
    # that didn't lead to an exception in generating the execution request for some reason, so we
    # check the extern exceptions list again.
    internal_errors = self._scheduler._native.cffi_extern_method_runtime_exceptions()
    if internal_errors:
      error_tracebacks = [
        ''.join(
          traceback.format_exception(etype=error_info.exc_type,
                                     value=error_info.exc_value,
                                     tb=error_info.traceback))
        for error_info in internal_errors
      ]

      raised_exception_message = None
      if raised_exception:
        exc_type, exc_value, tb = raised_exception
        raised_exception_message = dedent("""\
          The engine execution request raised this error, which is probably due to the errors in the
          CFFI extern methods listed above, as CFFI externs return None upon error:
          {}
        """).format(''.join(traceback.format_exception(etype=exc_type, value=exc_value, tb=tb)))

      # Zero out the errors raised in CFFI callbacks in case this one is caught and pants doesn't
      # exit.
      self._scheduler._native.reset_cffi_extern_method_runtime_exceptions()

      raise ExecutionError(dedent("""\
        {error_description} raised in CFFI extern methods:
        {joined_tracebacks}{raised_exception_message}
        """).format(
          error_description=pluralize(len(internal_errors), 'Exception'),
          joined_tracebacks='\n+++++++++\n'.join(formatted_tb for formatted_tb in error_tracebacks),
          raised_exception_message=(
            '\n\n{}'.format(raised_exception_message) if raised_exception_message else '')
        ))

    returns, throws = self.execute(request)

    # Throw handling.
    if throws:
      unique_exceptions = tuple({t.exc for _, t in throws})
      self._trace_on_error(unique_exceptions, request)

    # Everything is a Return: we rely on the fact that roots are ordered to preserve subject
    # order in output lists.
    return [ret.value for _, ret in returns]

  def capture_snapshots(self, path_globs_and_roots):
    """Synchronously captures Snapshots for each matching PathGlobs rooted at a its root directory.

    This is a blocking operation, and should be avoided where possible.

    :param path_globs_and_roots tuple<PathGlobsAndRoot>: The PathGlobs to capture, and the root
           directory relative to which each should be captured.
    :returns: A tuple of Snapshots.
    """
    return self._scheduler.capture_snapshots(path_globs_and_roots)

  def merge_directories(self, directory_digests):
    return self._scheduler.merge_directories(directory_digests)

  def materialize_directories(self, directories_paths_and_digests):
    """Creates the specified directories on the file system.

    :param directories_paths_and_digests tuple<DirectoryToMaterialize>: Tuple of the path and
           digest of the directories to materialize.
    :returns: Nothing or an error.
    """
    return self._scheduler.materialize_directories(directories_paths_and_digests)

  def lease_files_in_graph(self):
    self._scheduler.lease_files_in_graph()

  def garbage_collect_store(self):
    self._scheduler.garbage_collect_store()
