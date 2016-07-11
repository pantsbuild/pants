# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.isolated_process import ProcessExecutionNode, SnapshotNode
from pants.engine.nodes import (DependenciesNode, FilesystemNode, Node, Noop, Return, SelectNode,
                                State, StepContext, TaskNode, Throw, Waiting)
from pants.engine.objects import Closable
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

  def update_state(self, node, state):
    """Updates the Node with the given State, creating any Nodes which do not already exist."""
    entry = self.ensure_entry(node)
    if entry.state is not None:
      # It's important not to allow state changes on completed Nodes, because that invariant
      # is used in cycle detection to avoid walking into completed Nodes.
      raise CompletedNodeException('Node {} is already completed:\n  {}\n  {}'
                                   .format(node, entry.state, state))

    if type(state) in [Return, Throw, Noop]:
      # Validate that a completed Node depends only on other completed Nodes.
      for dep in entry.dependencies:
        if dep.state is None:
          raise IncompleteDependencyException(
              'Cannot complete {} with {} while it has an incomplete dep:\n  {}'
                .format(node, state, dep.node))
      entry.state = state
    elif type(state) is Waiting:
      self._add_dependencies(entry, state.dependencies)
    else:
      raise State.raise_unrecognized(state)

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
      logger.debug('invalidating node: %r', entry.node)
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
                                              entry.node.product.__name__,
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


class Promise(object):
  """An extremely simple _non-threadsafe_ Promise class."""

  def __init__(self):
    self._success = None
    self._failure = None
    self._is_complete = False

  def is_complete(self):
    return self._is_complete

  def success(self, success):
    self._success = success
    self._is_complete = True

  def failure(self, exception):
    self._failure = exception
    self._is_complete = True

  def get(self):
    """Returns the resulting value, or raises the resulting exception."""
    if not self._is_complete:
      raise ValueError('{} has not been completed.'.format(self))
    if self._failure:
      raise self._failure
    else:
      return self._success


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


class NodeBuilder(Closable):
  """Holds an index of tasks and intrinsics used to instantiate Nodes."""

  @classmethod
  def create(cls, task_entries):
    """Creates a NodeBuilder with tasks indexed by their output type."""
    serializable_tasks = defaultdict(set)
    for entry in task_entries:
      if isinstance(entry, (tuple, list)) and len(entry) == 3:
        output_type, input_selects, task = entry
        serializable_tasks[output_type].add(
          TaskNodeFactory(tuple(input_selects), task, output_type)
        )
      elif isinstance(entry, SnapshottedProcess):
        serializable_tasks[entry.output_product_type].add(entry)
      else:
        raise Exception("Unexpected type for entry {}".format(entry))

    intrinsics = dict()
    intrinsics.update(FilesystemNode.as_intrinsics())
    intrinsics.update(SnapshotNode.as_intrinsics())
    return cls(serializable_tasks, intrinsics)

  @classmethod
  def create_task_node(cls, subject, product_type, variants, task_func, clause):
    return TaskNode(subject, product_type, variants, task_func, clause)

  def __init__(self, tasks, intrinsics):
    self._tasks = tasks
    self._intrinsics = intrinsics

  def gen_nodes(self, subject, product_type, variants):
    # Intrinsics that provide the requested product for the current subject type.
    intrinsic_node_factory = self._lookup_intrinsic(product_type, subject)
    if intrinsic_node_factory:
      yield intrinsic_node_factory(subject, product_type, variants)
    else:
      # Tasks that provide the requested product.
      for node_factory in self._lookup_tasks(product_type):
        yield node_factory(subject, product_type, variants)

  def _lookup_tasks(self, product_type):
    for entry in self._tasks[product_type]:
      yield entry.as_node

  def _lookup_intrinsic(self, product_type, subject):
    return self._intrinsics.get((type(subject), product_type))


class StepRequest(datatype('Step', ['step_id', 'node', 'dependencies', 'inline_nodes', 'project_tree'])):
  """Additional inputs needed to run Node.step for the given Node.

  TODO: Unclear why this has a ProjectTree reference; should be passed in by the Engine.

  :param step_id: A unique id for the step, to ease comparison.
  :param node: The Node instance that will run.
  :param dependencies: The declared dependencies of the Node from previous Waiting steps.
  :param inline_nodes: See `LocalScheduler._inline_nodes`.
  :param project_tree: A FileSystemProjectTree instance.
  """

  def __call__(self, node_builder):
    """Called by the Engine in order to execute this Step."""
    step_context = StepContext(node_builder, self.project_tree, self.dependencies, self.inline_nodes)
    state = self.node.step(step_context)
    return StepResult(state)

  def __eq__(self, other):
    return type(self) == type(other) and self.step_id == other.step_id

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.step_id)


class StepResult(datatype('Step', ['state'])):
  """The result of running a Step, passed back to the Scheduler via the Promise class.

  :param state: The State value returned by the Step.
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
    self._step_id = 0

  def visualize_graph_to_file(self, roots, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock, open(filename, 'wb') as fh:
      for line in self.product_graph.visualize(roots):
        fh.write(line)
        fh.write('\n')

  def _create_step(self, node_entry):
    """Creates a Step and Promise with the currently available dependencies of the given Node.

    If the dependencies of a Node are not available, returns None.

    TODO: Content addressing node and its dependencies should only happen if node is cacheable
      or in a multi-process environment.
    """
    Node.validate_node(node_entry.node)

    # See whether all of the dependencies for the node are available.
    deps = dict()
    for dep_entry in node_entry.dependencies:
      if not dep_entry.is_complete:
        return None
      deps[dep_entry.node] = dep_entry.state
    # Additionally, include Noops for any dependencies that were cyclic.
    for dep in node_entry.cyclic_dependencies:
      deps[dep] = Noop.cycle(node_entry.node, dep)

    # Ready.
    self._step_id += 1
    step_request = StepRequest(self._step_id,
                               node_entry.node,
                               deps,
                               self._inline_nodes,
                               self._project_tree)
    return (step_request, Promise())

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
        for product in products:
          if type(subject) is Address:
            yield SelectNode(subject, product, None, None)
          elif type(subject) in [SingleAddress, SiblingAddresses, DescendantAddresses]:
            yield DependenciesNode(subject, product, None, Addresses, None)
          elif type(subject) is PathGlobs:
            yield SelectNode(subject, product, None, None)
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

  def _complete_step(self, node, step_result):
    """Given a StepResult for the given Node, complete the step."""
    result = step_result.state
    # Update the Node's state in the graph.
    self._product_graph.update_state(node, result)

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
      outstanding = {}
      # Node entries that might need to have Steps created (after any outstanding Step returns).
      candidates = set(self._product_graph.ensure_entry(r) for r in execution_request.roots)

      # Yield nodes that are ready, and then compute new ones.
      scheduling_iterations = 0
      start_time = time.time()
      while True:
        # Create Steps for candidates that are ready to run, and not already running.
        ready = dict()
        for candidate in list(candidates):
          if candidate in outstanding:
            # Node is still a candidate, but is currently running.
            continue
          if candidate.is_complete:
            # Node has already completed.
            candidates.discard(candidate)
            continue
          # Create a step if all dependencies are available; otherwise, can assume they are
          # outstanding, and will cause this Node to become a candidate again later.
          candidate_step = self._create_step(candidate)
          if candidate_step is not None:
            ready[candidate] = candidate_step
          candidates.discard(candidate)

        if not ready and not outstanding:
          # Finished.
          break
        yield ready.values()
        scheduling_iterations += 1
        outstanding.update(ready)

        # Finalize completed Steps.
        for node_entry, value in outstanding.items()[:]:
          step, promise = value
          if not promise.is_complete():
            continue
          # The step has completed; see whether the Node is completed.
          outstanding.pop(node_entry)
          self._complete_step(step.node, promise.get())
          if node_entry.is_complete:
            # The Node is completed: mark any of its dependents as candidates for Steps.
            candidates.update(d for d in node_entry.dependents)
          else:
            # Waiting on dependencies.
            incomplete_deps = [d for d in node_entry.dependencies if not d.is_complete]
            if incomplete_deps:
              # Mark incomplete deps as candidates for Steps.
              candidates.update(incomplete_deps)
            else:
              # All deps are already completed: mark this Node as a candidate for another step.
              candidates.add(node_entry)

      logger.debug(
        'ran %s scheduling iterations in %f seconds. '
        'there have been %s total steps for %s total nodes.',
        scheduling_iterations,
        time.time() - start_time,
        self._step_id,
        len(self._product_graph)
      )

      if self._graph_validator is not None:
        self._graph_validator.validate(self._product_graph)
