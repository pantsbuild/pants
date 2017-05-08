# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import threading
import time
from contextlib import contextmanager

from pants.base.project_tree import Dir, File, Link
from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import SubclassesOf
from pants.engine.fs import FileContent, FilesContent, Path, PathGlobs, Snapshot
from pants.engine.isolated_process import _Snapshots, create_snapshot_rules
from pants.engine.nodes import Return, Throw
from pants.engine.rules import RuleIndex, SingletonRule, TaskRule
from pants.engine.selectors import (Select, SelectDependencies, SelectProjection, SelectTransitive,
                                    SelectVariant, constraint_for)
from pants.engine.struct import HasProducts, Variants
from pants.engine.subsystem.native import Function, TypeConstraint, TypeId
from pants.util.contextutil import temporary_file_path
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExecutionRequest(datatype('ExecutionRequest', ['roots'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Roots for this request.
  :type roots: list of tuples of subject and product.
  """


class WrappedNativeScheduler(object):
  def __init__(self, native, build_root, work_dir, ignore_patterns, rule_index, root_subject_types):
    self._native = native
    # TODO: The only (?) case where we use inheritance rather than exact type unions.
    has_products_constraint = SubclassesOf(HasProducts)
    self._root_subject_types = sorted(root_subject_types)

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
      )

  def _root_type_ids(self):
    return self._to_ids_buf(sorted(self._root_subject_types))

  def graph_trace(self):
    with temporary_file_path() as path:
      self._native.lib.graph_trace(self._scheduler, bytes(path))
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
    return TypeConstraint(self._to_id(constraint_for(type_or_constraint)))

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
    self._native.lib.tasks_task_begin(self._tasks, Function(self._to_id(func)), output_constraint)
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

  def visualize_graph_to_file(self, filename):
    self._native.lib.graph_visualize(self._scheduler, bytes(filename))

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

    product_type_id = TypeConstraint(self._to_id(constraint_for(product_type)))
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

  def add_root_selection(self, subject, selector):
    if type(selector) is Select:
      self._native.lib.execution_add_root_select(self._scheduler, self._to_key(subject),
                                                 self._to_constraint(selector.product))
    elif type(selector) is SelectDependencies:
      self._native.lib.execution_add_root_select_dependencies(self._scheduler,
                                                              self._to_key(subject),
                                                              self._to_constraint(selector.product),
                                                              self._to_constraint(
                                                                selector.dep_product),
                                                              self._to_utf8_buf(selector.field),
                                                              self._to_ids_buf(
                                                                selector.field_types))
    else:
      raise ValueError('Unsupported root selector type: {}'.format(selector))

  def run_and_return_stat(self):
    return self._native.lib.execution_execute(self._scheduler)

  def visualize_to_dir(self):
    return self._native.visualize_to_dir

  def to_keys(self, subjects):
    return list(self._to_key(subject) for subject in subjects)

  def pre_fork(self):
    self._native.lib.scheduler_pre_fork(self._scheduler)

  def root_entries(self, execution_request):
    raw_roots = self._native.lib.execution_roots(self._scheduler)
    try:
      roots = {}
      for root, raw_root in zip(execution_request.roots,
                                self._native.unpack(raw_roots.nodes_ptr,
                                                    raw_roots.nodes_len)):
        if raw_root.state_tag is 0:
          state = None
        elif raw_root.state_tag is 1:
          state = Return(self._from_value(raw_root.state_value))
        elif raw_root.state_tag is 2:
          state = Throw(self._from_value(raw_root.state_value))
        elif raw_root.state_tag is 3:
          state = Throw(self._from_value(raw_root.state_value))
        else:
          raise ValueError(
            'Unrecognized State type `{}` on: {}'.format(raw_root.state_tag, raw_root))
        roots[root] = state
    finally:
      self._native.lib.nodes_destroy(raw_roots)
    return roots


class LocalScheduler(object):
  """A scheduler that expands a product Graph by executing user defined Rules."""

  def __init__(self,
               work_dir,
               goals,
               rules,
               project_tree,
               native,
               graph_lock=None):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param rules: A set of Rules which is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param work_dir: The pants work dir.
    :param native: An instance of engine.subsystem.native.Native.
    :param graph_lock: A re-entrant lock to use for guarding access to the internal product Graph
                       instance. Defaults to creating a new threading.RLock().
    """
    self._products_by_goal = goals
    self._project_tree = project_tree
    self._product_graph_lock = graph_lock or threading.RLock()
    self._run_count = 0

    # Create the ExternContext, and the native Scheduler.
    self._execution_request = None


    # Validate and register all provided and intrinsic tasks.
    # TODO: This bounding of input Subject types allows for closed-world validation, but is not
    # strictly necessary for execution. We might eventually be able to remove it by only executing
    # validation below the execution roots (and thus not considering paths that aren't in use).

    root_subject_types = {
      Address,
      BuildFileAddress,
      AscendantAddresses,
      DescendantAddresses,
      PathGlobs,
      SiblingAddresses,
      SingleAddress,
    }
    rules = list(rules) + create_snapshot_rules()
    rule_index = RuleIndex.create(rules)
    self._scheduler = WrappedNativeScheduler(native,
                                             project_tree.build_root,
                                             work_dir,
                                             project_tree.ignore_patterns,
                                             rule_index,
                                             root_subject_types)

    # If configured, visualize the rule graph before asserting that it is valid.
    if self._scheduler.visualize_to_dir() is not None:
      rule_graph_name = 'rule_graph.dot'
      self.visualize_rule_graph_to_file(os.path.join(self._scheduler.visualize_to_dir(), rule_graph_name))

    self._scheduler.assert_ruleset_valid()

  def trace(self):
    """Yields a stringified 'stacktrace' starting from the scheduler's roots."""
    with self._product_graph_lock:
      for line in self._scheduler.graph_trace():
        yield line

  def visualize_graph_to_file(self, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock:
      self._scheduler.visualize_graph_to_file(filename)

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
    return ExecutionRequest(tuple((s, Select(p)) for s in subjects for p in products))

  def selection_request(self, requests):
    """Create and return an ExecutionRequest for the given (selector, subject) tuples.

    This method allows users to specify their own selectors. It has the potential to replace
    execution_request, which is a subset of this method, because it uses default selectors.
    :param requests: A list of (selector, subject) tuples.
    :return: An ExecutionRequest for the given selectors and subjects.
    """
    #TODO: Think about how to deprecate the existing execution_request API.
    return ExecutionRequest(tuple((subject, selector) for selector, subject in requests))

  @contextmanager
  def locked(self):
    with self._product_graph_lock:
      yield

  def root_entries(self, execution_request):
    """Returns the roots for the given ExecutionRequest as a dict of tuples to State."""
    with self._product_graph_lock:
      if self._execution_request is not execution_request:
        raise AssertionError(
          "Multiple concurrent executions are not supported! {} vs {}".format(
            self._execution_request, execution_request))
      return self._scheduler.root_entries(execution_request)

  def invalidate_files(self, filenames):
    """Calls `Graph.invalidate_files()` against an internal product Graph instance."""
    # NB: Watchman will never trigger an invalidation event for the root directory that
    # is being watched. Instead, we treat any invalidation of a path directly in the
    # root directory as an invalidation of the root.
    if any(os.path.dirname(f) in ('', '.') for f in filenames):
      filenames = tuple(filenames) + ('', '.')
    with self._product_graph_lock:
      invalidated = self._scheduler.invalidate(filenames)
      logger.debug('invalidated %d nodes for: %s', invalidated, filenames)
      return invalidated

  def node_count(self):
    with self._product_graph_lock:
      return self._scheduler.graph_len()

  def _execution_add_roots(self, execution_request):
    if self._execution_request is not None:
      self._scheduler.exec_reset()
    self._execution_request = execution_request
    for subject, selector in execution_request.roots:
      self._scheduler.add_root_selection(subject, selector)

  def pre_fork(self):
    self._scheduler.pre_fork()

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """

    with self._product_graph_lock:
      start_time = time.time()
      # Reset execution, and add any roots from the request.
      self._execution_add_roots(execution_request)
      # Execute in native engine.
      execution_stat = self._scheduler.run_and_return_stat()
      # Receive execution statistics.
      runnable_count = execution_stat.runnable_count
      scheduling_iterations = execution_stat.scheduling_iterations

      if self._scheduler.visualize_to_dir() is not None:
        name = 'run.{}.dot'.format(self._run_count)
        self._run_count += 1
        self.visualize_graph_to_file(os.path.join(self._scheduler.visualize_to_dir(), name))

      logger.debug(
        'ran %s scheduling iterations and %s runnables in %f seconds. '
        'there are %s total nodes.',
        scheduling_iterations,
        runnable_count,
        time.time() - start_time,
        self._scheduler.graph_len()
      )
