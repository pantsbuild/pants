# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import time
from builtins import object, open, str, zip
from collections import defaultdict
from types import GeneratorType

from pants.base.exceptions import TaskError
from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.fs import (DirectoryDigest, DirectoryToMaterialize, FileContent, FilesContent,
                             MergedDirectories, Path, PathGlobs, PathGlobsAndRoot, Snapshot)
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.native import Function, TypeConstraint, TypeId
from pants.engine.nodes import Return, State, Throw
from pants.engine.rules import RuleIndex, SingletonRule, TaskRule
from pants.engine.selectors import Select, constraint_for
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import check_no_overlapping_paths
from pants.util.objects import Collection, datatype
from pants.util.strutil import pluralize


logger = logging.getLogger(__name__)


class ExecutionRequest(datatype(['roots', 'native'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `SchedulerSession.execution_request`.

  :param roots: Roots for this request.
  :type roots: list of tuples of subject and product.
  """


class ExecutionResult(datatype(['error', 'root_products'])):
  """Represents the result of a single execution."""

  @classmethod
  def finished(cls, root_products):
    """Create a success or partial success result from a finished run.

    Runs can either finish with no errors, satisfying all promises, or they can partially finish
    if run in fail-slow mode producing as many products as possible.
    :param root_products: List of ((subject, product), State) tuples.
    :rtype: `ExecutionResult`
    """
    return cls(error=None, root_products=root_products)

  @classmethod
  def failure(cls, error):
    """Create a failure result.

    A failure result represent a run with a fatal error.  It presents the error but no
    products.

    :param error: The execution error encountered.
    :type error: :class:`pants.base.exceptions.TaskError`
    :rtype: `ExecutionResult`
    """
    return cls(error=error, root_products=None)


class ExecutionError(Exception):
  def __init__(self, message, wrapped_exceptions=None):
    super(ExecutionError, self).__init__(message)
    self.wrapped_exceptions = wrapped_exceptions or ()


class Scheduler(object):
  def __init__(
    self,
    native,
    project_tree,
    work_dir,
    rules,
    execution_options,
    include_trace_on_error=True,
    validate=True,
  ):
    """
    :param native: An instance of engine.native.Native.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param work_dir: The pants work dir.
    :param rules: A set of Rules which is used to compute values in the graph.
    :param execution_options: Execution options for (remote) processes.
    :param include_trace_on_error: Include the trace through the graph upon encountering errors.
    :type include_trace_on_error: bool
    :param validate: True to assert that the ruleset is valid.
    """

    if execution_options.remote_execution_server and not execution_options.remote_store_server:
      raise ValueError("Cannot set remote execution server without setting remote store server")

    self._native = native
    self.include_trace_on_error = include_trace_on_error

    # Validate and register all provided and intrinsic tasks.
    rule_index = RuleIndex.create(list(rules))
    self._root_subject_types = sorted(rule_index.roots, key=repr)

    # Create the native Scheduler and Session.
    # TODO: This `_tasks` reference could be a local variable, since it is not used
    # after construction.
    self._tasks = native.new_tasks()
    self._register_rules(rule_index)

    self._scheduler = native.new_scheduler(
      tasks=self._tasks,
      root_subject_types=self._root_subject_types,
      build_root=project_tree.build_root,
      work_dir=work_dir,
      ignore_patterns=project_tree.ignore_patterns,
      execution_options=execution_options,
      construct_directory_digest=DirectoryDigest,
      construct_snapshot=Snapshot,
      construct_file_content=FileContent,
      construct_files_content=FilesContent,
      construct_path_stat=Path,
      construct_dir=Dir,
      construct_file=File,
      construct_link=Link,
      construct_process_result=FallibleExecuteProcessResult,
      constraint_address=constraint_for(Address),
      constraint_path_globs=constraint_for(PathGlobs),
      constraint_directory_digest=constraint_for(DirectoryDigest),
      constraint_snapshot=constraint_for(Snapshot),
      constraint_merge_snapshots_request=constraint_for(MergedDirectories),
      constraint_files_content=constraint_for(FilesContent),
      constraint_dir=constraint_for(Dir),
      constraint_file=constraint_for(File),
      constraint_link=constraint_for(Link),
      constraint_process_request=constraint_for(ExecuteProcessRequest),
      constraint_process_result=constraint_for(FallibleExecuteProcessResult),
      constraint_generator=constraint_for(GeneratorType),
    )

    # If configured, visualize the rule graph before asserting that it is valid.
    if self.visualize_to_dir() is not None:
      rule_graph_name = 'rule_graph.dot'
      self.visualize_rule_graph_to_file(os.path.join(self.visualize_to_dir(), rule_graph_name))

    if validate:
      self._assert_ruleset_valid()

  def _root_type_ids(self):
    return self._to_ids_buf(sorted(self._root_subject_types, key=repr))

  def graph_trace(self, execution_request):
    with temporary_file_path() as path:
      self._native.lib.graph_trace(self._scheduler, execution_request, path.encode('utf-8'))
      with open(path, 'r') as fd:
        for line in fd.readlines():
          yield line.rstrip()

  def _assert_ruleset_valid(self):
    self._raise_or_return(self._native.lib.validator_run(self._scheduler))

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

  def _from_id(self, cdata):
    return self._native.context.from_id(cdata)

  def _from_key(self, cdata):
    return self._native.context.from_key(cdata)

  def _to_constraint(self, type_or_constraint):
    return TypeConstraint(self._to_key(constraint_for(type_or_constraint)))

  def _to_ids_buf(self, types):
    return self._native.to_ids_buf(types)

  def _to_utf8_buf(self, string):
    return self._native.context.utf8_buf(string)

  def _register_rules(self, rule_index):
    """Record the given RuleIndex on `self._tasks`."""
    registered = set()
    for product_type, rules in rule_index.rules.items():
      # TODO: The rules map has heterogeneous keys, so we normalize them to type constraints
      # and dedupe them before registering to the native engine:
      #   see: https://github.com/pantsbuild/pants/issues/4005
      output_constraint = self._to_constraint(product_type)
      for rule in rules:
        key = (output_constraint, rule)
        if key in registered:
          continue
        registered.add(key)

        if type(rule) is SingletonRule:
          self._register_singleton(output_constraint, rule)
        elif type(rule) is TaskRule:
          self._register_task(output_constraint, rule)
        else:
          raise ValueError('Unexpected Rule type: {}'.format(rule))

  def _register_singleton(self, output_constraint, rule):
    """Register the given SingletonRule.

    A SingletonRule installed for a type will be the only provider for that type.
    """
    self._native.lib.tasks_singleton_add(self._tasks,
                                         self._to_value(rule.value),
                                         output_constraint)

  def _register_task(self, output_constraint, rule):
    """Register the given TaskRule with the native scheduler."""
    func = Function(self._to_key(rule.func))
    self._native.lib.tasks_task_begin(self._tasks, func, output_constraint)
    for selector in rule.input_selectors:
      selector_type = type(selector)
      product_constraint = self._to_constraint(selector.product)
      if selector_type is Select:
        self._native.lib.tasks_add_select(self._tasks, product_constraint)
      else:
        raise ValueError('Unrecognized Selector type: {}'.format(selector))
    for get in rule.input_gets:
      self._native.lib.tasks_add_get(self._tasks,
                                     self._to_constraint(get.product),
                                     TypeId(self._to_id(get.subject)))
    self._native.lib.tasks_task_end(self._tasks)

  def visualize_graph_to_file(self, session, filename):
    res = self._native.lib.graph_visualize(self._scheduler, session, filename.encode('utf-8'))
    self._raise_or_return(res)

  def visualize_rule_graph_to_file(self, filename):
    self._native.lib.rule_graph_visualize(
      self._scheduler,
      self._root_type_ids(),
      filename.encode('utf-8'))

  def rule_graph_visualization(self):
    with temporary_file_path() as path:
      self.visualize_rule_graph_to_file(path)
      with open(path) as fd:
        for line in fd.readlines():
          yield line.rstrip()

  def rule_subgraph_visualization(self, root_subject_type, product_type):
    root_type_id = TypeId(self._to_id(root_subject_type))

    product_type_id = TypeConstraint(self._to_key(constraint_for(product_type)))
    with temporary_file_path() as path:
      self._native.lib.rule_subgraph_visualize(
        self._scheduler,
        root_type_id,
        product_type_id,
        path.encode('utf-8'))
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

  def add_root_selection(self, execution_request, subject, product):
    res = self._native.lib.execution_add_root_select(self._scheduler,
                                                     execution_request,
                                                     self._to_key(subject),
                                                     self._to_constraint(product))
    self._raise_or_return(res)

  def visualize_to_dir(self):
    return self._native.visualize_to_dir

  def _metrics(self, session):
    metrics_val = self._native.lib.scheduler_metrics(self._scheduler, session)
    return {k: v for k, v in self._from_value(metrics_val)}

  def with_fork_context(self, func):
    """See the rustdocs for `scheduler_fork_context` for more information."""
    res = self._native.lib.scheduler_fork_context(self._scheduler, Function(self._to_key(func)))
    return self._raise_or_return(res)

  def _run_and_return_roots(self, session, execution_request):
    raw_roots = self._native.lib.scheduler_execute(self._scheduler, session, execution_request)
    try:
      roots = []
      for raw_root in self._native.unpack(raw_roots.nodes_ptr, raw_roots.nodes_len):
        if raw_root.state_tag is 1:
          state = Return(self._from_value(raw_root.state_value))
        elif raw_root.state_tag in (2, 3):
          state = Throw(self._from_value(raw_root.state_value))
        else:
          raise ValueError(
            'Unrecognized State type `{}` on: {}'.format(raw_root.state_tag, raw_root))
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
    :return: A DirectoryDigest.
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

  def new_session(self):
    """Creates a new SchedulerSession for this Scheduler."""
    return SchedulerSession(self, self._native.new_session(self._scheduler))


_PathGlobsAndRootCollection = Collection.of(PathGlobsAndRoot)


_DirectoryDigests = Collection.of(DirectoryDigest)


_DirectoriesToMaterialize = Collection.of(DirectoryToMaterialize)


class SchedulerSession(object):
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

  def with_fork_context(self, func):
    return self._scheduler.with_fork_context(func)

  def _maybe_visualize(self):
    if self._scheduler.visualize_to_dir() is not None:
      name = 'graph.{0:03d}.dot'.format(self._run_count)
      self._run_count += 1
      self.visualize_graph_to_file(os.path.join(self._scheduler.visualize_to_dir(), name))

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
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

    return roots

  def execute(self, execution_request):
    """Executes the requested build and returns the resulting root entries.

    TODO: Merge with `schedule`.
    TODO2: Use of TaskError here is... odd.

    :param execution_request: The description of the goals to achieve.
    :type execution_request: :class:`ExecutionRequest`
    :returns: The result of the run.
    :rtype: :class:`Engine.Result`
    """
    try:
      return ExecutionResult.finished(self.schedule(execution_request))
    except TaskError as e:
      return ExecutionResult.failure(e)

  def products_request(self, products, subjects):
    """Executes a request for multiple products for some subjects, and returns the products.

    :param list products: A list of product type for the request.
    :param list subjects: A list of subjects for the request.
    :returns: A dict from product type to lists of products each with length matching len(subjects).
    """
    request = self.execution_request(products, subjects)
    result = self.execute(request)
    if result.error:
      raise result.error

    # State validation.
    unknown_state_types = tuple(
      type(state) for _, state in result.root_products if type(state) not in (Throw, Return)
    )
    if unknown_state_types:
      State.raise_unrecognized(unknown_state_types)

    # Throw handling.
    # TODO: See https://github.com/pantsbuild/pants/issues/3912
    throw_root_states = tuple(state for root, state in result.root_products if type(state) is Throw)
    if throw_root_states:
      unique_exceptions = tuple({t.exc for t in throw_root_states})
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

    # Everything is a Return: we rely on the fact that roots are ordered to preserve subject
    # order in output lists.
    product_results = defaultdict(list)
    for (_, product), state in result.root_products:
      product_results[product].append(state.value)
    return product_results

  def product_request(self, product, subjects):
    """Executes a request for a single product for some subjects, and returns the products.

    :param class product: A product type for the request.
    :param list subjects: A list of subjects for the request.
    :returns: A list of the requested products, with length match len(subjects).
    """
    return self.products_request([product], subjects)[product]

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
