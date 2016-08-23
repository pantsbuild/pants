# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
import functools

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.fs import PathGlobs, create_fs_intrinsics
from pants.engine.graph import Graph
from pants.engine.subsystem.native import extern_isinstance, extern_store_list
from pants.engine.isolated_process import ProcessExecutionNode, SnapshotNode
from pants.engine.nodes import (DependenciesNode, FilesystemNode, Noop, Runnable, SelectNode,
                                StepContext, TaskNode, Waiting, Return, Throw)
from pants.engine.objects import Closable
from pants.engine.selectors import (Select, SelectDependencies, SelectLiteral, SelectProjection,
                                    SelectVariant)
from pants.util.objects import datatype
from pants.engine.struct import HasProducts, Variants


logger = logging.getLogger(__name__)


class ExecutionRequest(datatype('ExecutionRequest', ['roots'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Roots for this request.
  :type roots: list of tuples of subject and product.
  """


class SnapshottedProcess(datatype('SnapshottedProcess', ['product_type',
                                                         'binary_type',
                                                         'input_selectors',
                                                         'input_conversion',
                                                         'output_conversion'])):
  """A task type for defining execution of snapshotted processes."""

  def as_node(self, subject, product_type, variants):
    return ProcessExecutionNode(subject, variants, self)

  @property
  def output_product_type(self):
    return self.product_type

  @property
  def input_selects(self):
    return self.input_selectors


class TaskNodeFactory(datatype('Task', ['input_selects', 'task_func', 'product_type'])):
  """A set-friendly curried TaskNode constructor."""

  def as_node(self, subject, product_type, variants):
    return TaskNode(subject, product_type, variants, self.task_func, self.input_selects)


class LocalScheduler(object):
  """A scheduler that expands a product Graph by executing user defined tasks."""

  def __init__(self,
               goals,
               tasks,
               storage,
               project_tree,
               native,
               graph_lock=None,
               graph_validator=None):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param native: An instance of engine.subsystem.native.Native.
    :param graph_lock: A re-entrant lock to use for guarding access to the internal product Graph
                       instance. Defaults to creating a new threading.RLock().
    :param graph_validator: A validator that runs over the entire graph after every scheduling
                            attempt. Very expensive, very experimental.
    """
    self._products_by_goal = goals
    self._project_tree = project_tree
    self._storage = storage
    self._native = native
    self._product_graph_lock = graph_lock or threading.RLock()

    # Create the scheduler.
    self._storage_handle = native.new_handle(storage)
    scheduler = native.lib.scheduler_create(self._storage_handle,
                                            extern_isinstance,
                                            extern_store_list,
                                            self._to_key('name'),
                                            self._to_key('products'),
                                            self._to_key('default'),
                                            self._to_type_key(Address),
                                            self._to_type_key(HasProducts),
                                            self._to_type_key(Variants))
    self._scheduler = native.gc(scheduler, native.lib.scheduler_destroy)
    # Register all "intrinsic" tasks.
    self._register_intrinsics()
    # Register all provided tasks.
    for task in tasks:
      self._register_task(task)

  def _register_intrinsics(self):
    """Register any "intrinsic" tasks.
    
    Intrinsic tasks are those that are the default for a particular type(subject), type(product)
    pair. By default, intrinsic tasks create Runnables that are not cacheable.
    """
    for func, subject_type, product_type in create_fs_intrinsics():
      # Create a pickleable function for the task with the ProjectTree included.
      pfunc = functools.partial(func, self._project_tree)
      self._native.lib.intrinsic_task_add(self._scheduler,
                                          self._to_type_key(pfunc),
                                          self._to_type_key(subject_type),
                                          self._to_type_key(product_type))

  def _register_task(self, task):
    """Register the given task triple with the native scheduler."""
    output_type, input_selects, func = task
    self._native.lib.task_add(self._scheduler,
                              self._to_type_key(func),
                              self._to_type_key(output_type))
    for selector in input_selects:
      selector_type = type(selector)
      if selector_type is Select:
        self._native.lib.task_add_select(self._scheduler,
                                         self._to_type_key(selector.product))
      elif selector_type is SelectVariant:
        self._native.lib.task_add_select_variant(self._scheduler,
                                                 self._to_type_key(selector.product),
                                                 self._to_key(selector.variant_key))
      elif selector_type is SelectLiteral:
        # NB: Intentionally ignores subject parameter to provide a literal subject.
        self._native.lib.task_add_select_literal(self._scheduler,
                                                 self._to_key(selector.subject),
                                                 self._to_type_key(selector.product))
      elif selector_type is SelectDependencies:
        self._native.lib.task_add_select_dependencies(self._scheduler,
                                                      self._to_type_key(selector.product),
                                                      self._to_type_key(selector.dep_product),
                                                      self._to_key(selector.field))
      elif selector_type is SelectProjection:
        if len(selector.fields) != 1:
          raise ValueError("TODO: remove support for projecting multiple fields at once.")
        field = selector.fields[0]
        self._native.lib.task_add_select_projection(self._scheduler,
                                                    self._to_type_key(selector.product),
                                                    self._to_type_key(selector.projected_subject),
                                                    self._to_key(field),
                                                    self._to_type_key(selector.input_product))
      else:
        raise ValueError('Unrecognized Selector type: {}'.format(selector))
    self._native.lib.task_end(self._scheduler)

  def _to_digest(self, obj):
    return (self._storage.put(obj).digest,)

  def _to_type_key(self, t):
    return self._to_digest(t)

  def _to_key(self, obj):
    return (self._to_digest(obj), self._to_digest(type(obj)))

  def _from_type_key(self, cdata):
    return self._storage.get_from_digest(self._native.buffer(cdata.digest)[:])

  def _from_key(self, cdata):
    return self._storage.get_from_digest(self._native.buffer(cdata.digest.digest)[:])

  def visualize_graph_to_file(self, roots, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock, open(filename, 'wb') as fh:
      for line in self.product_graph.visualize(roots):
        fh.write(line)
        fh.write('\n')

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

    return ExecutionRequest(tuple((s, p) for s in subjects for p in products))

  @contextmanager
  def locked(self):
    with self._product_graph_lock:
      yield

  def root_entries(self, execution_request):
    """Returns the roots for the given ExecutionRequest as a dict from Node to State."""
    with self._product_graph_lock:
      return {root: self._product_graph.state(root) for root in execution_request.roots}

  def invalidate_files(self, filenames):
    """Calls `Graph.invalidate_files()` against an internal product Graph instance."""
    with self._product_graph_lock:
      subjects = set(FilesystemNode.generate_subjects(filenames))

      def predicate(node, state):
        return type(node) is FilesystemNode and node.subject in subjects

      return self._product_graph.invalidate(predicate)

  def _execution_next(self, completed):
    # Unzip into two arrays.
    returns_ids, returns_states, throws_ids = [], [], []
    for cid, c in completed:
      if type(c) is Return:
        returns_ids.append(cid)
        returns_states.append(self._to_key(c.value))
      elif type(c) is Throw:
        throws_ids.append(cid)
      else:
        raise ValueError("Unexpected `Completed` state from Runnable execution: {}".format(c))

    # Run, then collect the outputs from the Scheduler's RawExecution struct.
    self._native.lib.execution_next(self._scheduler,
                                    returns_ids,
                                    returns_states,
                                    len(returns_ids),
                                    throws_ids,
                                    len(throws_ids))
    def runnable(raw):
      return Runnable(self._from_type_key(raw.func),
                      tuple(self._from_key(key)
                            for key in self._native.unpack(raw.args_ptr, raw.args_len)),
                      bool(raw.cacheable))

    runnable_ids = self._native.unpack(self._scheduler.execution.ready_ptr,
                                       self._scheduler.execution.ready_len)
    runnable_states = [runnable(r) for r in
                        self._native.unpack(self._scheduler.execution.ready_runnables_ptr,
                                            self._scheduler.execution.ready_len)]
    # Rezip from two arrays.
    return zip(runnable_ids, runnable_states)

  def _execution_add_roots(self, execution_request):
    self._native.lib.execution_reset(self._scheduler)
    for subject, product in execution_request.roots:
      if type(subject) in [Address, PathGlobs]:
        self._native.lib.execution_add_root_select(
            self._scheduler,
            self._to_key(subject),
            self._to_type_key(product))
      elif type(subject) in [SingleAddress, SiblingAddresses, DescendantAddresses]:
        self._native.lib.execution_add_root_select_dependencies(
            self._scheduler,
            self._to_key(subject),
            self._to_type_key(product),
            self._to_type_key(Addresses),
            self._to_key('dependencies'))
      else:
        raise ValueError('Unsupported root subject type: {}'.format(subject))

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

      # Yield nodes that are Runnable, and then compute new ones.
      completed = []
      outstanding_runnable = dict()
      runnable_count, scheduling_iterations = 0, 0
      while True:
        # Call the scheduler to create Runnables for the Engine.
        runnable = self._execution_next(completed)
        if not runnable and not outstanding_runnable:
          # Finished.
          break
        completed = yield runnable
        yield
        runnable_count += len(runnable)
        scheduling_iterations += 1

      logger.debug(
        'ran %s scheduling iterations and %s runnables in %f seconds. '
        'there are %s total nodes.',
        scheduling_iterations,
        runnable_count,
        time.time() - start_time,
        self._native.lib.graph_len(self._scheduler)
      )
