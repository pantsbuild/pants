# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import time
from collections import defaultdict

from pants.base.exceptions import TaskError
from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.addressable import SubclassesOf
from pants.engine.fs import FileContent, FilesContent, Path, PathGlobs, Snapshot
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult, _Snapshots,
                                           create_snapshot_rules)
from pants.engine.native import Function, TypeConstraint, TypeId
from pants.engine.nodes import Return, State, Throw
from pants.engine.rules import RuleIndex, SingletonRule, TaskRule
from pants.engine.selectors import (Select, SelectDependencies, SelectProjection, SelectTransitive,
                                    SelectVariant, constraint_for)
from pants.engine.struct import HasProducts, Variants
from pants.util.contextutil import temporary_file_path
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExecutionRequest(datatype('ExecutionRequest', ['roots', 'native'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Roots for this request.
  :type roots: list of tuples of subject and product.
  """


class ExecutionResult(datatype('ExecutionResult', ['error', 'root_products'])):
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
  pass


class WrappedNativeScheduler(object):
  def __init__(self, native, build_root, work_dir, ignore_patterns, rule_index):
    self._native = native
    # TODO: The only (?) case where we use inheritance rather than exact type unions.
    has_products_constraint = SubclassesOf(HasProducts)
    self._root_subject_types = sorted(rule_index.roots)

    # Create the ExternContext, and the native Scheduler.
    self._tasks = native.new_tasks()
    self._register_rules(rule_index)

    self._scheduler = native.new_scheduler(
      self._tasks,
      self._root_subject_types,
      build_root,
      work_dir,
      ignore_patterns,
      Snapshot,
      _Snapshots,
      FileContent,
      FilesContent,
      Path,
      Dir,
      File,
      Link,
      ExecuteProcessResult,
      has_products_constraint,
      constraint_for(Address),
      constraint_for(Variants),
      constraint_for(PathGlobs),
      constraint_for(Snapshot),
      constraint_for(_Snapshots),
      constraint_for(FilesContent),
      constraint_for(Dir),
      constraint_for(File),
      constraint_for(Link),
      constraint_for(ExecuteProcessRequest),
      constraint_for(ExecuteProcessResult),
    )

  def _root_type_ids(self):
    return self._to_ids_buf(sorted(self._root_subject_types))

  def graph_trace(self, execution_request):
    with temporary_file_path() as path:
      self._native.lib.graph_trace(self._scheduler, execution_request, bytes(path))
      with open(path) as fd:
        for line in fd.readlines():
          yield line.rstrip()

  def assert_ruleset_valid(self):
    raw_value = self._native.lib.validator_run(self._scheduler)
    value = self._from_value(raw_value)

    if isinstance(value, Exception):
      raise ValueError(str(value))

  def _to_value(self, obj):
    return self._native.context.to_value(obj)

  def _from_value(self, val):
    return self._native.context.from_value(val)

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
    input_selects = rule.input_selectors
    func = rule.func
    self._native.lib.tasks_task_begin(self._tasks, Function(self._to_key(func)), output_constraint)
    for selector in input_selects:
      selector_type = type(selector)
      product_constraint = self._to_constraint(selector.product)
      if selector_type is Select:
        self._native.lib.tasks_add_select(self._tasks, product_constraint)
      elif selector_type is SelectVariant:
        key_buf = self._to_utf8_buf(selector.variant_key)
        self._native.lib.tasks_add_select_variant(self._tasks,
                                                  product_constraint,
                                                  key_buf)
      elif selector_type is SelectDependencies:
        self._native.lib.tasks_add_select_dependencies(self._tasks,
                                                       product_constraint,
                                                       self._to_constraint(selector.dep_product),
                                                       self._to_utf8_buf(selector.field),
                                                       self._to_ids_buf(selector.field_types))
      elif selector_type is SelectTransitive:
        self._native.lib.tasks_add_select_transitive(self._tasks,
                                                     product_constraint,
                                                     self._to_constraint(selector.dep_product),
                                                     self._to_utf8_buf(selector.field),
                                                     self._to_ids_buf(selector.field_types))
      elif selector_type is SelectProjection:
        self._native.lib.tasks_add_select_projection(self._tasks,
                                                     self._to_constraint(selector.product),
                                                     TypeId(self._to_id(selector.projected_subject)),
                                                     self._to_utf8_buf(selector.field),
                                                     self._to_constraint(selector.input_product))
      else:
        raise ValueError('Unrecognized Selector type: {}'.format(selector))
    self._native.lib.tasks_task_end(self._tasks)

  def visualize_graph_to_file(self, execution_request, filename):
    self._native.lib.graph_visualize(self._scheduler, execution_request, bytes(filename))

  def visualize_rule_graph_to_file(self, filename):
    self._native.lib.rule_graph_visualize(
      self._scheduler,
      self._root_type_ids(),
      bytes(filename))

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
        bytes(path))
      with open(path) as fd:
        for line in fd.readlines():
          yield line.rstrip()

  def invalidate(self, filenames):
    filenames_buf = self._native.context.utf8_buf_buf(filenames)
    return self._native.lib.graph_invalidate(self._scheduler, filenames_buf)

  def graph_len(self):
    return self._native.lib.graph_len(self._scheduler)

  def exec_reset(self):
    self._native.lib.execution_reset(self._scheduler)

  def add_root_selection(self, execution_request, subject, product):
    res = self._native.lib.execution_add_root_select(self._scheduler,
                                                     execution_request,
                                                     self._to_key(subject),
                                                     self._to_constraint(product))
    if res.is_throw:
      raise self._from_value(res.value)

  def visualize_to_dir(self):
    return self._native.visualize_to_dir

  def to_keys(self, subjects):
    return list(self._to_key(subject) for subject in subjects)

  def pre_fork(self):
    self._native.lib.scheduler_pre_fork(self._scheduler)

  def run_and_return_roots(self, execution_request):
    raw_roots = self._native.lib.execution_execute(self._scheduler, execution_request)
    try:
      roots = []
      for raw_root in self._native.unpack(raw_roots.nodes_ptr, raw_roots.nodes_len):
        if raw_root.state_tag is 1:
          state = Return(self._from_value(raw_root.state_value))
        elif raw_root.state_tag in (2, 3, 4):
          state = Throw(self._from_value(raw_root.state_value))
        else:
          raise ValueError(
            'Unrecognized State type `{}` on: {}'.format(raw_root.state_tag, raw_root))
        roots.append(state)
    finally:
      self._native.lib.nodes_destroy(raw_roots)
    return roots

  def lease_files_in_graph(self):
    self._native.lib.lease_files_in_graph(self._scheduler)

  def garbage_collect_store(self):
    self._native.lib.garbage_collect_store(self._scheduler)


class LocalScheduler(object):
  """A scheduler that expands a product Graph by executing user defined Rules."""

  def __init__(self,
               work_dir,
               goals,
               rules,
               project_tree,
               native,
               include_trace_on_error=True):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param rules: A set of Rules which is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param work_dir: The pants work dir.
    :param native: An instance of engine.native.Native.
    :param include_trace_on_error: Include the trace through the graph upon encountering errors.
    :type include_trace_on_error: bool
    """
    self._products_by_goal = goals
    self._project_tree = project_tree
    self._include_trace_on_error = include_trace_on_error
    self._run_count = 0

    # Create the ExternContext, and the native Scheduler.
    self._execution_request = None

    # Validate and register all provided and intrinsic tasks.
    rules = list(rules) + create_snapshot_rules()
    rule_index = RuleIndex.create(rules)
    self._scheduler = WrappedNativeScheduler(native,
                                             project_tree.build_root,
                                             work_dir,
                                             project_tree.ignore_patterns,
                                             rule_index)

    # If configured, visualize the rule graph before asserting that it is valid.
    if self._scheduler.visualize_to_dir() is not None:
      rule_graph_name = 'rule_graph.dot'
      self.visualize_rule_graph_to_file(os.path.join(self._scheduler.visualize_to_dir(), rule_graph_name))

    self._scheduler.assert_ruleset_valid()

  def graph_len(self):
    return self._scheduler.graph_len()

  def trace(self, execution_request):
    """Yields a stringified 'stacktrace' starting from the scheduler's roots."""
    for line in self._scheduler.graph_trace(execution_request.native):
      yield line

  def visualize_graph_to_file(self, execution_request, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param ExecutionRequest execution_request: A set of roots to visualize from.
    :param str filename: The filename to output the graphviz output to.
    """
    self._scheduler.visualize_graph_to_file(execution_request.native, filename)

  def visualize_rule_graph_to_file(self, filename):
    self._scheduler.visualize_rule_graph_to_file(filename)

  def build_request(self, goals, subjects):
    """Translate the given goal names into product types, and return an ExecutionRequest.

    :param goals: The list of goal names supplied on the command line.
    :type goals: list of string
    :param subjects: A list of Spec and/or PathGlobs objects.
    :type subject: list of :class:`pants.base.specs.Spec`, `pants.build_graph.Address`, and/or
      :class:`pants.engine.fs.PathGlobs` objects.
    :returns: An ExecutionRequest for the given goals and subjects.
    """
    return self.execution_request([self._products_by_goal[goal_name] for goal_name in goals],
                                  subjects)

  def execution_request(self, products, subjects):
    """Create and return an ExecutionRequest for the given products and subjects.

    The resulting ExecutionRequest object will contain keys tied to this scheduler's product Graph, and
    so it will not be directly usable with other scheduler instances without being re-created.

    An ExecutionRequest for an Address represents exactly one product output, as does SingleAddress. But
    we differentiate between them here in order to normalize the output for all Spec objects
    as "list of product".

    :param products: A list of product types to request for the roots.
    :type products: list of types
    :param subjects: A list of Spec and/or PathGlobs objects.
    :type subject: list of :class:`pants.base.specs.Spec`, `pants.build_graph.Address`, and/or
      :class:`pants.engine.fs.PathGlobs` objects.
    :returns: An ExecutionRequest for the given products and subjects.
    """
    roots = tuple((s, p) for s in subjects for p in products)
    native_execution_request = self._scheduler._native.new_execution_request()
    for subject, product in roots:
      self._scheduler.add_root_selection(native_execution_request, subject, product)
    return ExecutionRequest(roots, native_execution_request)

  def invalidate_files(self, direct_filenames):
    """Calls `Graph.invalidate_files()` against an internal product Graph instance."""
    # NB: Watchman no longer triggers events when children are created/deleted under a directory,
    # so we always need to invalidate the direct parent as well.
    filenames = set(direct_filenames)
    filenames.update(os.path.dirname(f) for f in direct_filenames)
    invalidated = self._scheduler.invalidate(filenames)
    logger.info('invalidated %d nodes for: %s', invalidated, filenames)
    return invalidated

  def node_count(self):
    return self._scheduler.graph_len()

  def pre_fork(self):
    self._scheduler.pre_fork()

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """
    start_time = time.time()
    roots = zip(execution_request.roots,
                self._scheduler.run_and_return_roots(execution_request.native))

    if self._scheduler.visualize_to_dir() is not None:
      name = 'run.{}.dot'.format(self._run_count)
      self._run_count += 1
      self.visualize_graph_to_file(execution_request,
                                   os.path.join(self._scheduler.visualize_to_dir(), name))

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
      if self._include_trace_on_error:
        cumulative_trace = '\n'.join(self.trace(request))
        raise ExecutionError('Received unexpected Throw state(s):\n{}'.format(cumulative_trace))

      unique_exceptions = set(t.exc for t in throw_root_states)
      if len(unique_exceptions) == 1:
        raise throw_root_states[0].exc
      else:
        raise ExecutionError('Multiple exceptions encountered:\n  {}'
                             .format('\n  '.join('{}: {}'.format(type(t).__name__, str(t))
                                                                 for t in unique_exceptions)))

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

  def lease_files_in_graph(self):
    self._scheduler.lease_files_in_graph()

  def garbage_collect_store(self):
    self._scheduler.garbage_collect_store()
