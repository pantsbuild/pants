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

from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address
from pants.engine.addressable import SubclassesOf
from pants.engine.fs import PathGlobs, create_fs_intrinsics, generate_fs_subjects
from pants.engine.isolated_process import create_snapshot_singletons
from pants.engine.nodes import Return, Throw
from pants.engine.rules import RuleIndex, RulesetValidator
from pants.engine.selectors import (Select, SelectDependencies, SelectLiteral, SelectProjection,
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


class LocalScheduler(object):
  """A scheduler that expands a product Graph by executing user defined tasks."""

  def __init__(self,
               goals,
               tasks,
               project_tree,
               native,
               graph_lock=None):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param native: An instance of engine.subsystem.native.Native.
    :param graph_lock: A re-entrant lock to use for guarding access to the internal product Graph
                       instance. Defaults to creating a new threading.RLock().
    """
    self._products_by_goal = goals
    self._project_tree = project_tree
    self._native = native
    self._product_graph_lock = graph_lock or threading.RLock()
    self._run_count = 0

    # TODO: The only (?) case where we use inheritance rather than exact type unions.
    has_products_constraint = SubclassesOf(HasProducts)

    # Create the ExternContext, and the native Scheduler.
    self._scheduler = native.new_scheduler(has_products_constraint,
                                           constraint_for(Address),
                                           constraint_for(Variants))
    self._execution_request = None

    # Validate and register all provided and intrinsic tasks.
    # TODO: This bounding of input Subject types allows for closed-world validation, but is not
    # strictly necessary for execution. We might eventually be able to remove it by only executing
    # validation below the execution roots (and thus not considering paths that aren't in use).
    select_product = lambda product: Select(product)
    root_selector_fns = {
      Address: select_product,
      AscendantAddresses: select_product,
      DescendantAddresses: select_product,
      PathGlobs: select_product,
      SiblingAddresses: select_product,
      SingleAddress: select_product,
    }
    intrinsics = create_fs_intrinsics(project_tree)
    singletons = create_snapshot_singletons(project_tree)
    rule_index = RuleIndex.create(tasks, intrinsics, singletons)
    RulesetValidator(rule_index, goals, root_selector_fns).validate()
    self._register_tasks(rule_index.tasks)
    self._register_intrinsics(rule_index.intrinsics)
    self._register_singletons(rule_index.singletons)

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

  def _register_singletons(self, singletons):
    """Register the given singletons dict.

    Singleton tasks are those that are the default for a particular type(product). Like
    intrinsics, singleton tasks create Runnables that are not cacheable.
    """
    for product_type, rule in singletons.items():
      self._native.lib.singleton_task_add(self._scheduler,
                                          Function(self._to_id(rule.func)),
                                          self._to_constraint(product_type))

  def _register_intrinsics(self, intrinsics):
    """Register the given intrinsics dict.

    Intrinsic tasks are those that are the default for a particular type(subject), type(product)
    pair. By default, intrinsic tasks create Runnables that are not cacheable.
    """
    for (subject_type, product_type), rule in intrinsics.items():
      self._native.lib.intrinsic_task_add(self._scheduler,
                                          Function(self._to_id(rule.func)),
                                          TypeId(self._to_id(subject_type)),
                                          self._to_constraint(subject_type),
                                          self._to_constraint(product_type))

  def _register_tasks(self, tasks):
    """Register the given tasks dict with the native scheduler."""
    registered = set()
    for output_type, rules in tasks.items():
      output_constraint = self._to_constraint(output_type)
      for rule in rules:
        # TODO: The task map has heterogeneous keys, so we normalize them to type constraints
        # and dedupe them before registering to the native engine:
        #   see: https://github.com/pantsbuild/pants/issues/4005
        key = (output_constraint, rule)
        if key in registered:
          continue
        registered.add(key)

        _, input_selects, func = rule.as_triple()
        self._native.lib.task_add(self._scheduler, Function(self._to_id(func)), output_constraint)
        for selector in input_selects:
          selector_type = type(selector)
          product_constraint = self._to_constraint(selector.product)
          if selector_type is Select:
            self._native.lib.task_add_select(self._scheduler,
                                             product_constraint)
          elif selector_type is SelectVariant:
            key_buf = self._native.context.utf8_buf(selector.variant_key)
            self._native.lib.task_add_select_variant(self._scheduler,
                                                     product_constraint,
                                                     key_buf)
          elif selector_type is SelectLiteral:
            # NB: Intentionally ignores subject parameter to provide a literal subject.
            self._native.lib.task_add_select_literal(self._scheduler,
                                                     self._to_key(selector.subject),
                                                     product_constraint)
          elif selector_type is SelectDependencies:
            self._native.lib.task_add_select_dependencies(self._scheduler,
                                                          product_constraint,
                                                          self._to_constraint(selector.dep_product),
                                                          self._to_key(selector.field),
                                                          selector.transitive)
          elif selector_type is SelectProjection:
            if len(selector.fields) != 1:
              raise ValueError("TODO: remove support for projecting multiple fields at once.")
            field = selector.fields[0]
            self._native.lib.task_add_select_projection(self._scheduler,
                                                        self._to_constraint(selector.product),
                                                        TypeId(self._to_id(selector.projected_subject)),
                                                        self._to_key(field),
                                                        self._to_constraint(selector.input_product))
          else:
            raise ValueError('Unrecognized Selector type: {}'.format(selector))
        self._native.lib.task_end(self._scheduler)

  def trace(self):
    """Yields a stringified 'stacktrace' starting from the scheduler's roots."""
    with self._product_graph_lock:
      with temporary_file_path() as path:
        self._native.lib.graph_trace(self._scheduler, bytes(path))
        with open(path) as fd:
          for line in fd.readlines():
            yield line.rstrip()

  def visualize_graph_to_file(self, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock:
      self._native.lib.graph_visualize(self._scheduler, bytes(filename))

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
      raw_roots = self._native.gc(self._native.lib.execution_roots(self._scheduler),
                                  self._native.lib.nodes_destroy)
      roots = {}
      for root, raw_root in zip(execution_request.roots, self._native.unpack(raw_roots.nodes_ptr, raw_roots.nodes_len)):
        if raw_root.union_tag is 0:
          state = None
        elif raw_root.union_tag is 1:
          state = Return(self._from_value(raw_root.union_return))
        elif raw_root.union_tag is 2:
          state = Throw(self._from_value(raw_root.union_throw))
        elif raw_root.union_tag is 3:
          state = Throw(Exception("Nooped"))
        else:
          raise ValueError('Unrecognized State type `{}` on: {}'.format(raw_root.union_tag, raw_root))
        roots[root] = state
      return roots

  def invalidate_files(self, filenames):
    """Calls `Graph.invalidate_files()` against an internal product Graph instance."""
    subjects = set(generate_fs_subjects(filenames))
    subject_keys = list(self._to_key(subject) for subject in subjects)
    with self._product_graph_lock:
      invalidated = self._native.lib.graph_invalidate(self._scheduler,
                                                      subject_keys,
                                                      len(subject_keys))
      logger.debug('invalidated %d nodes for subjects: %s', invalidated, subjects)
      return invalidated

  def node_count(self):
    with self._product_graph_lock:
      return self._native.lib.graph_len(self._scheduler)

  def _execution_add_roots(self, execution_request):
    if self._execution_request is not None:
      self._native.lib.execution_reset(self._scheduler)
    self._execution_request = execution_request
    for subject, selector in execution_request.roots:
      if type(selector) is Select:
        self._native.lib.execution_add_root_select(self._scheduler,
                                                   self._to_key(subject),
                                                   self._to_constraint(selector.product))
      elif type(selector) is SelectDependencies:
        self._native.lib.execution_add_root_select_dependencies(self._scheduler,
                                                                self._to_key(subject),
                                                                self._to_constraint(selector.product),
                                                                self._to_constraint(selector.dep_product),
                                                                self._to_key(selector.field),
                                                                selector.transitive)
      else:
        raise ValueError('Unsupported root selector type: {}'.format(selector))

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
      execution_stat = self._native.lib.execution_execute(self._scheduler)
      # Receive execution statistics.
      runnable_count = execution_stat.runnable_count
      scheduling_iterations = execution_stat.scheduling_iterations

      if self._native.visualize_to_dir is not None:
        name = 'run.{}.dot'.format(self._run_count)
        self._run_count += 1
        self.visualize_graph_to_file(os.path.join(self._native.visualize_to_dir, name))

      logger.debug(
        'ran %s scheduling iterations and %s runnables in %f seconds. '
        'there are %s total nodes.',
        scheduling_iterations,
        runnable_count,
        time.time() - start_time,
        self._native.lib.graph_len(self._scheduler)
      )
