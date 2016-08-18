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

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.graph import Graph
from pants.engine.isolated_process import ProcessExecutionNode, SnapshotNode
from pants.engine.nodes import (DependenciesNode, FilesystemNode, Noop, Runnable, SelectNode,
                                StepContext, TaskNode, Waiting)
from pants.engine.objects import Closable
from pants.engine.selectors import Select, SelectDependencies
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExecutionRequest(datatype('ExecutionRequest', ['roots'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Root Nodes for this request.
  :type roots: list of :class:`pants.engine.nodes.Node`
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

    self._native = native
    self._product_graph_lock = graph_lock or threading.RLock()

    # Create the scheduler.
    self._scheduler = native.gc(native.lib.scheduler_create(),
                                native.lib.scheduler_destroy)
    # And register all provided tasks.
    for output_type, input_selects, func in tasks:
      self._native.lib.task_gen(self._scheduler, func, output_type)
      for input_select in input_selects:
        self._native.lib.task_add_select_literal(self._scheduler,
                                                 input_select.subject,
                                                 input_select.product)
      self._native.lib.task_end(self._scheduler)

  def visualize_graph_to_file(self, roots, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock, open(filename, 'wb') as fh:
      for line in self.product_graph.visualize(roots):
        fh.write(line)
        fh.write('\n')

  def _run_step(self, node_entry, dep_states):
    """Attempt to run a Step with the currently available dependencies of the given Node.

    If the currently declared dependencies of a Node are not yet available, returns None. If
    they are available, runs a Step and returns the resulting State.
    """
    # Initialize the coroutine if this is the first time it is running.
    if node_entry.coroutine is None:
      if dep_states:
        raise ValueError('{} has not run yet, and should not have dependencies!'.format(node_entry))
      node_entry.coroutine = node_entry.node.step(self._step_context)
      return node_entry.coroutine.send(None)
    else:
      return node_entry.coroutine.send(dep_states)

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

    # Determine the root Nodes for the products and subjects selected by the goals and specs.
    def roots():
      for subject in subjects:
        for product in products:
          if type(subject) in [Address, PathGlobs]:
            yield SelectNode(subject, None, Select(product))
          elif type(subject) in [SingleAddress, SiblingAddresses, DescendantAddresses]:
            yield DependenciesNode(subject, None, SelectDependencies(product, Addresses))
          else:
            raise ValueError('Unsupported root subject type: {}'.format(subject))

    return ExecutionRequest(tuple(roots()))

  @property
  def product_graph(self):
    return self._product_graph

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
    # Run, then collect the outputs from the Scheduler's RawExecution struct.
    self._native.lib.execution_next(self._scheduler, completed)
    return zip(
        self._native.unpack(self._scheduler.execution.ready_ptr,
                            self._scheduler.execution.ready_len),
        self._native.unpack(self._scheduler.execution.ready_runnables_ptr,
                            self._scheduler.execution.ready_len)
      )

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """

    with self._product_graph_lock:
      # Reset execution, then add any roots from the request.
      self._native.lib.execution_reset(self._scheduler)
      for r in execution_request.roots:
        self._native.lib.execution_add_root_select(self._scheduler, r)

      # Yield nodes that are Runnable, and then compute new ones.
      completed = []
      outstanding_runnable = dict()
      step_count, runnable_count, scheduling_iterations = 0, 0, 0
      start_time = time.time()
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
        'ran %s scheduling iterations, %s runnables, and %s steps in %f seconds. '
        'there are %s total nodes.',
        scheduling_iterations,
        runnable_count,
        step_count,
        time.time() - start_time,
        len(self._product_graph)
      )

      if self._graph_validator is not None:
        self._graph_validator.validate(self._product_graph)
