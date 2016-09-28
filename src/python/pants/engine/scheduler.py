# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import threading
import time
from collections import deque
from contextlib import contextmanager

from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.nodes import (FilesystemNode, Node, Noop, Return, Runnable, SelectNode,
                                StepContext, TaskNode, Throw, Waiting)
from pants.engine.rules import NodeBuilder, RulesetValidator
from pants.engine.selectors import Select, SelectDependencies, type_or_constraint_repr
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class CompletedNodeException(ValueError):
  """Indicates an attempt to change a Node that is already completed."""


class IncompleteDependencyException(ValueError):
  """Indicates an attempt to complete a Node that has incomplete dependencies."""


class ProductGraph(object):

  class Entry(object):
    """An entry representing a Node in the ProductGraph.

    Equality for this object is intentionally `identity` for efficiency purposes: structural
    equality can be implemented by comparing the result of the `structure` method.
    """
    __slots__ = ('node', 'state', 'dependencies', 'dependents', 'cyclic_dependencies')

    def __init__(self, node):
      self.node = node
      # The computed value for a Node: if a Node hasn't been computed yet, it will be None.
      self.state = None
      # Sets of dependency/dependent Entry objects.
      self.dependencies = set()
      self.dependents = set()
      # Illegal/cyclic dependency Nodes. We prevent cyclic dependencies from being introduced into the
      # dependencies/dependents lists themselves, but track them independently in order to provide
      # context specific error messages when they are introduced.
      self.cyclic_dependencies = set()

    @property
    def is_complete(self):
      return self.state is not None

    def validate_not_complete(self):
      if self.is_complete:
        # It's important not to allow state changes on completed Nodes, because that invariant
        # is used in cycle detection to avoid walking into completed Nodes.
        raise CompletedNodeException('Node {} is already completed with:\n  {}'
                                    .format(self.node, self.state))

    def set_state(self, state):
      self.validate_not_complete()

      # Validate that a completed Node depends only on other completed Nodes.
      for dep in self.dependencies:
        if not dep.is_complete:
          raise IncompleteDependencyException(
              'Cannot complete {} with {} while it has an incomplete dep:\n  {}'
                .format(self, state, dep.node))

      # Finally, set.
      self.state = state

    def structure(self):
      return (self.node,
              self.state,
              {d.node for d in self.dependencies},
              {d.node for d in self.dependents},
              self.cyclic_dependencies)

  def __init__(self, validator=None):
    self._validator = validator or Node.validate_node
    # A dict of Node->Entry.
    self._nodes = dict()

  def __len__(self):
    return len(self._nodes)

  def is_complete(self, node):
    entry = self._nodes.get(node, None)
    return entry and entry.is_complete

  def state(self, node):
    entry = self._nodes.get(node, None)
    if not entry:
      return None
    return entry.state

  def complete_node(self, node, state):
    """Updates the Node with the given State, creating any Nodes which do not already exist."""
    if type(state) not in (Return, Throw, Noop):
      raise ValueError('A Node may only be completed with a final State. Got: {}'.format(state))
    entry = self.ensure_entry(node)
    entry.set_state(state)

  def add_dependencies(self, node, dependencies):
    entry = self.ensure_entry(node)
    entry.validate_not_complete()
    self._add_dependencies(entry, dependencies)

  def _detect_cycle(self, src, dest):
    """Detect whether adding an edge from src to dest would create a cycle.

    :param src: Source entry: must exist in the graph.
    :param dest: Destination entry: must exist in the graph.

    Returns True if a cycle would be created by adding an edge from src->dest.
    """
    # We disallow adding new edges outbound from completed Nodes, and no completed Node can have
    # a path to an uncompleted Node. Thus, we can truncate our search for cycles at any completed
    # Node.
    is_not_completed = lambda e: e.state is None
    for entry in self._walk_entries([dest], entry_predicate=is_not_completed):
      if entry is src:
        return True
    return False

  def ensure_entry(self, node):
    """Returns the Entry for the given Node, creating it if it does not already exist."""
    entry = self._nodes.get(node, None)
    if not entry:
      self._validator(node)
      self._nodes[node] = entry = self.Entry(node)
    return entry

  def _add_dependencies(self, node_entry, dependencies):
    """Adds dependency edges from the given src Node to the given dependency Nodes.

    Executes cycle detection: if adding one of the given dependencies would create
    a cycle, then the _source_ Node is marked as a Noop with an error indicating the
    cycle path, and the dependencies are not introduced.
    """

    # Add deps. Any deps which would cause a cycle are added to cyclic_dependencies instead,
    # and ignored except for the purposes of Step execution.
    for dependency in dependencies:
      dependency_entry = self.ensure_entry(dependency)
      if dependency_entry in node_entry.dependencies:
        continue

      if self._detect_cycle(node_entry, dependency_entry):
        node_entry.cyclic_dependencies.add(dependency)
      else:
        node_entry.dependencies.add(dependency_entry)
        dependency_entry.dependents.add(node_entry)

  def completed_nodes(self):
    """In linear time, yields the states of any Nodes which have completed."""
    for node, entry in self._nodes.items():
      if entry.state is not None:
        yield node, entry.state

  def dependents(self):
    """In linear time, yields the dependents lists for all Nodes."""
    for node, entry in self._nodes.items():
      yield node, [d.node for d in entry.dependents]

  def dependencies(self):
    """In linear time, yields the dependencies lists for all Nodes."""
    for node, entry in self._nodes.items():
      yield node, [d.node for d in entry.dependencies]

  def cyclic_dependencies(self):
    """In linear time, yields the cyclic_dependencies lists for all Nodes."""
    for node, entry in self._nodes.items():
      yield node, entry.cyclic_dependencies

  def dependents_of(self, node):
    entry = self._nodes.get(node, None)
    if entry:
      for d in entry.dependents:
        yield d.node

  def _dependency_entries_of(self, node):
    entry = self._nodes.get(node, None)
    if entry:
      for d in entry.dependencies:
        yield d

  def dependencies_of(self, node):
    for d in self._dependency_entries_of(node):
      yield d.node

  def cyclic_dependencies_of(self, node):
    entry = self._nodes.get(node, None)
    if not entry:
      return set()
    return entry.cyclic_dependencies

  def invalidate(self, predicate=None):
    """Invalidate nodes and their subgraph of dependents given a predicate.

    :param func predicate: A predicate that matches Node objects for all nodes in the graph.
    """
    def _sever_dependents(entry):
      for associated_entry in entry.dependencies:
        associated_entry.dependents.discard(entry)

    def _delete_node(entry):
      actual_entry = self._nodes.pop(entry.node)
      assert entry is actual_entry

    def all_predicate(node, state): return True
    predicate = predicate or all_predicate

    invalidated_root_entries = list(entry for entry in self._nodes.values()
                                    if predicate(entry.node, entry.state))
    invalidated_entries = list(entry for entry in self._walk_entries(invalidated_root_entries,
                                                                     lambda _: True,
                                                                     dependents=True))

    # Sever dependee->dependent relationships in the graph for all given invalidated nodes.
    for entry in invalidated_entries:
      _sever_dependents(entry)

    # Delete all nodes based on a backwards walk of the graph from all matching invalidated roots.
    for entry in invalidated_entries:
      _delete_node(entry)

    invalidated_count = len(invalidated_entries)
    logger.info('invalidated {} of {} nodes'.format(invalidated_count, len(self)))
    return invalidated_count

  def invalidate_files(self, filenames):
    """Given a set of changed filenames, invalidate all related FilesystemNodes in the graph."""
    subjects = set(FilesystemNode.generate_subjects(filenames))
    logger.debug('generated invalidation subjects: %s', subjects)

    def predicate(node, state):
      return type(node) is FilesystemNode and node.subject in subjects

    return self.invalidate(predicate)

  def walk(self, roots, predicate=None, dependents=False):
    """Yields Nodes and their States depth-first in pre-order, starting from the given roots.

    Each node entry is a tuple of (Node, State).

    The given predicate is applied to entries, and eliminates the subgraphs represented by nodes
    that don't match it. The default predicate eliminates all `Noop` subgraphs.
    """
    def _default_entry_predicate(entry):
      return type(entry.state) is not Noop
    def _entry_predicate(entry):
      return predicate(entry.node, entry.state)
    entry_predicate = _entry_predicate if predicate else _default_entry_predicate

    root_entries = []
    for root in roots:
      entry = self._nodes.get(root, None)
      if entry:
        root_entries.append(entry)

    for entry in self._walk_entries(root_entries, entry_predicate, dependents=dependents):
      yield (entry.node, entry.state)

  def _walk_entries(self, root_entries, entry_predicate, dependents=False):
    stack = deque(root_entries)
    walked = set()
    while stack:
      entry = stack.pop()
      if entry in walked:
        continue
      walked.add(entry)
      if not entry_predicate(entry):
        continue
      stack.extend(entry.dependents if dependents else entry.dependencies)

      yield entry

  def trace(self, root):
    """Yields a stringified 'stacktrace' starting from the given failed root.

    TODO: This could use polish. In particular, the `__str__` representations of Nodes and
    States are probably not sufficient for user output.
    """

    traced = set()

    def is_bottom(entry):
      return type(entry.state) in (Noop, Return) or entry in traced

    def is_one_level_above_bottom(parent_entry):
      return all(is_bottom(child_entry) for child_entry in parent_entry.dependencies)

    def _format(level, entry, state):
      output = '{}Computing {} for {}'.format('  ' * level,
                                              type_or_constraint_repr(entry.node.product),
                                              entry.node.subject)
      if is_one_level_above_bottom(entry):
        output += '\n{}{}'.format('  ' * (level + 1), state)

      return output

    def _trace(entry, level):
      if is_bottom(entry):
        return
      traced.add(entry)
      yield _format(level, entry, entry.state)
      for dep in entry.cyclic_dependencies:
        yield _format(level, entry, Noop.cycle(entry.node, dep))
      for dep_entry in entry.dependencies:
        for l in _trace(dep_entry, level+1):
          yield l

    for line in _trace(self._nodes[root], 1):
      yield line

  def visualize(self, roots):
    """Visualize a graph walk by generating graphviz `dot` output.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    """
    viz_colors = {}
    viz_color_scheme = 'set312'  # NB: There are only 12 colors in `set312`.
    viz_max_colors = 12

    def format_color(node, node_state):
      if type(node_state) is Throw:
        return 'tomato'
      elif type(node_state) is Noop:
        return 'white'
      return viz_colors.setdefault(node.product, (len(viz_colors) % viz_max_colors) + 1)

    def format_type(node):
      return node.func.__name__ if type(node) is TaskNode else type(node).__name__

    def format_subject(node):
      if node.variants:
        return '({})@{}'.format(node.subject,
                                ','.join('{}={}'.format(k, v) for k, v in node.variants))
      else:
        return '({})'.format(node.subject)

    def format_product(node):
      if type(node) is SelectNode and node.variant_key:
        return '{}@{}'.format(node.product.__name__, node.variant_key)
      return node.product.__name__

    def format_node(node, state):
      return '{}:{}:{} == {}'.format(format_product(node),
                                     format_subject(node),
                                     format_type(node),
                                     str(state).replace('"', '\\"'))

    def format_edge(src_str, dest_str, cyclic):
      style = " [style=dashed]" if cyclic else ""
      return '    "{}" -> "{}"{}'.format(node_str, format_node(dep, dep_state), style)

    yield 'digraph plans {'
    yield '  node[colorscheme={}];'.format(viz_color_scheme)
    yield '  concentrate=true;'
    yield '  rankdir=LR;'

    predicate = lambda n, s: type(s) is not Noop

    for (node, node_state) in self.walk(roots, predicate=predicate):
      node_str = format_node(node, node_state)

      yield '  "{}" [style=filled, fillcolor={}];'.format(node_str, format_color(node, node_state))

      for cyclic, adjacencies in ((False, self.dependencies_of), (True, self.cyclic_dependencies_of)):
        for dep in adjacencies(node):
          dep_state = self.state(dep)
          if not predicate(dep, dep_state):
            continue
          yield format_edge(node_str, format_node(dep, dep_state), cyclic)

    yield '}'


class ExecutionRequest(datatype('ExecutionRequest', ['roots'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Root Nodes for this request.
  :type roots: list of :class:`pants.engine.nodes.Node`
  """


class LocalScheduler(object):
  """A scheduler that expands a ProductGraph by executing user defined tasks."""

  def __init__(self,
               goals,
               tasks,
               project_tree,
               graph_lock=None,
               inline_nodes=True,
               graph_validator=None):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param graph_lock: A re-entrant lock to use for guarding access to the internal ProductGraph
                       instance. Defaults to creating a new threading.RLock().
    :param inline_nodes: Whether to inline execution of `inlineable` Nodes. This improves
                         performance, but can make debugging more difficult because the entire
                         execution history is not recorded in the ProductGraph.
    :param graph_validator: A validator that runs over the entire graph after every scheduling
                            attempt. Very expensive, very experimental.
    """
    self._products_by_goal = goals
    self._project_tree = project_tree
    self._node_builder = NodeBuilder.create(tasks)

    self._graph_validator = graph_validator
    self._product_graph = ProductGraph()
    self._product_graph_lock = graph_lock or threading.RLock()
    self._inline_nodes = inline_nodes

    select_product = lambda product: Select(product)
    select_dep_addrs = lambda product: SelectDependencies(product, Addresses, field_types=(Address,))
    self._root_selector_fns = {
      Address: select_product,
      PathGlobs: select_product,
      SingleAddress: select_dep_addrs,
      SiblingAddresses: select_dep_addrs,
      AscendantAddresses: select_dep_addrs,
      DescendantAddresses: select_dep_addrs,
    }

    RulesetValidator(self._node_builder, goals, self._root_selector_fns).validate()

  def visualize_graph_to_file(self, roots, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock, open(filename, 'wb') as fh:
      for line in self.product_graph.visualize(roots):
        fh.write(line)
        fh.write('\n')

  def _attempt_run_step(self, node_entry):
    """Attempt to run a Step with the currently available dependencies of the given Node.

    If the currently declared dependencies of a Node are not yet available, returns None. If
    they are available, runs a Step and returns the resulting State.
    """
    # See whether all of the dependencies for the node are available.
    if any(not dep_entry.is_complete for dep_entry in node_entry.dependencies):
      return None

    # Collect the deps.
    deps = dict()
    for dep_entry in node_entry.dependencies:
      deps[dep_entry.node] = dep_entry.state
    # Additionally, include Noops for any dependencies that were cyclic.
    for dep in node_entry.cyclic_dependencies:
      deps[dep] = Noop.cycle(node_entry.node, dep)

    # Run.
    step_context = StepContext(self.node_builder, self._project_tree, deps, self._inline_nodes)
    return node_entry.node.step(step_context)

  @property
  def node_builder(self):
    """Return the NodeBuilder instance for this Scheduler.

    A NodeBuilder is a relatively heavyweight object (since it contains an index of all
    registered tasks), so it should be used for the execution of multiple Steps.
    """
    return self._node_builder

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

    The resulting ExecutionRequest object will contain keys tied to this scheduler's ProductGraph, and
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
        selector_fn = self._root_selector_fns.get(type(subject), None)
        if not selector_fn:
          raise TypeError('Unsupported root subject type: {} for {!r}'
                          .format(type(subject), subject))

        for product in products:
          yield self._node_builder.select_node(selector_fn(product), subject, None)

    return ExecutionRequest(tuple(roots()))

  def selection_request(self, requests):
    """Create and return an ExecutionRequest for the given (selector, subject) tuples.

    This method allows users to specify their own selectors. It has the potential to replace
    execution_request, which is a subset of this method, because it uses default selectors.
    :param requests: A list of (selector, subject) tuples.
    :return: An ExecutionRequest for the given selectors and subjects.
    """
    #TODO: Think about how to deprecate the existing execution_request API.
    roots = (self._node_builder.select_node(selector, subject, None) for (selector, subject) in requests)
    return ExecutionRequest(tuple(roots))

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
    """Calls `ProductGraph.invalidate_files()` against an internal ProductGraph instance
    under protection of a scheduler-level lock."""
    with self._product_graph_lock:
      return self._product_graph.invalidate_files(filenames)

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """

    with self._product_graph_lock:
      # A dict from Node entry to a possibly executing Step. Only one Step exists for a Node at a time.
      outstanding = set()
      # Node entries that might need to have Steps created (after any outstanding Step returns).
      candidates = deque(self._product_graph.ensure_entry(r) for r in execution_request.roots)

      # Yield nodes that are Runnable, and then compute new ones.
      step_count, runnable_count, scheduling_iterations = 0, 0, 0
      start_time = time.time()
      while True:
        # Drain the candidate list to create Runnables for the Engine.
        runnable = []
        while candidates:
          node_entry = candidates.popleft()
          if node_entry.is_complete or node_entry in outstanding:
            # Node has already completed, or is runnable
            continue
          # Create a step if all dependencies are available; otherwise, can assume they are
          # outstanding, and will cause this Node to become a candidate again later.
          state = self._attempt_run_step(node_entry)
          if state is None:
            # No state change.
            continue

          # The Node's state is changing due to this Step.
          step_count += 1
          if type(state) is Runnable:
            # The Node is ready to run in the Engine.
            runnable.append((node_entry, state))
            outstanding.add(node_entry)
          elif type(state) is Waiting:
            # Waiting on dependencies.
            self._product_graph.add_dependencies(node_entry.node, state.dependencies)
            incomplete_deps = [d for d in node_entry.dependencies if not d.is_complete]
            if incomplete_deps:
              # Mark incomplete deps as candidates for Steps.
              candidates.extend(incomplete_deps)
            else:
              # All deps are already completed: mark this Node as a candidate for another step.
              candidates.append(node_entry)
          else:
            # The Node has completed statically.
            self._product_graph.complete_node(node_entry.node, state)
            candidates.extend(d for d in node_entry.dependents)

        if not runnable and not outstanding:
          # Finished.
          break
        # The double yield here is intentional, and assumes consumption of this generator in
        # a `for` loop with a `generator.send(completed)` call in the body of the loop.
        completed = yield runnable
        yield
        runnable_count += len(runnable)
        scheduling_iterations += 1

        # Finalize any Runnables that completed in the previous round.
        for node_entry, state in completed:
          # Complete the Node and mark any of its dependents as candidates for Steps.
          outstanding.discard(node_entry)
          self._product_graph.complete_node(node_entry.node, state)
          candidates.extend(d for d in node_entry.dependents)

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
