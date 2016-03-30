# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import threading
from collections import defaultdict

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.exp.addressable import Addresses
from pants.engine.exp.fs import PathGlobs, Paths
from pants.engine.exp.nodes import (DependenciesNode, FilesystemNode, Node, Noop, ProjectionNode,
                                    Return, SelectNode, State, StepContext, TaskNode, Throw,
                                    Waiting)
from pants.engine.exp.objects import Closable
from pants.engine.exp.selectors import (Select, SelectDependencies, SelectLiteral, SelectProjection,
                                        SelectVariant)
from pants.util.objects import datatype


class ProductGraph(object):

  def __init__(self, validator=None):
    self._validator = validator or Node.validate_node

    # A dict from Node to its computed value: if a Node hasn't been computed yet, it will not
    # be present here.
    self._node_results = dict()
    # Dicts from Nodes to sets of dependency/dependent Nodes.
    self._dependencies = defaultdict(set)
    self._dependents = defaultdict(set)
    # Illegal/cyclic dependencies. We prevent cyclic dependencies from being introduced into the
    # dependencies/dependents lists themselves, but track them independently in order to provide
    # context specific error messages when they are introduced.
    self._cyclic_dependencies = defaultdict(set)

  def _set_state(self, node, state):
    existing_state = self._node_results.get(node, None)
    if existing_state is not None:
      raise ValueError('Node {} is already completed:\n  {}\n  {}'
                       .format(node, existing_state, state))
    elif type(state) not in [Return, Throw, Noop]:
      raise ValueError('Cannot complete Node {} with state {}'.format(node, state))
    self._node_results[node] = state

  def is_complete(self, node):
    return node in self._node_results

  def state(self, node):
    return self._node_results.get(node, None)

  def update_state(self, node, state):
    """Updates the Node with the given State."""
    if type(state) in [Return, Throw, Noop]:
      self._set_state(node, state)
    elif type(state) is Waiting:
      self._add_dependencies(node, state.dependencies)
    else:
      raise State.raise_unrecognized(state)

  def _detect_cycle(self, src, dest):
    """Given a src and a dest, each of which _might_ already exist in the graph, detect cycles.

    Returns True if a cycle would be created by adding an edge from src->dest.
    """
    parents = set()
    walked = set()
    def _walk(node):
      if node in parents:
        return True
      if node in walked:
        return False
      parents.add(node)
      walked.add(node)

      for dep in self.dependencies_of(node):
        found = _walk(dep)
        if found:
          return found
      parents.discard(node)
      return False

    # Initialize the path with src (since the edge from src->dest may not actually exist), and
    # then walk from the dest.
    parents.add(src)
    return _walk(dest)

  def _add_dependencies(self, node, dependencies):
    """Adds dependency edges from the given src Node to the given dependency Nodes.

    Executes cycle detection: if adding one of the given dependencies would create
    a cycle, then the _source_ Node is marked as a Noop with an error indicating the
    cycle path, and the dependencies are not introduced.
    """
    self._validator(node)
    if self.is_complete(node):
      raise ValueError('Node {} is already completed, and cannot be updated.'.format(node))

    # Add deps. Any deps which would cause a cycle are added to _cyclic_dependencies instead,
    # and ignored except for the purposes of Step execution.
    node_dependencies = self._dependencies[node]
    node_cyclic_dependencies = self._cyclic_dependencies[node]
    for dependency in dependencies:
      if dependency in node_dependencies:
        continue
      self._validator(dependency)
      if self._detect_cycle(node, dependency):
        node_cyclic_dependencies.add(dependency)
      else:
        node_dependencies.add(dependency)
        self._dependents[dependency].add(node)
        # 'touch' the dependencies dict for this dependency, to ensure that an entry exists.
        self._dependencies[dependency]

  def completed_nodes(self):
    return self._node_results

  def dependents(self):
    return self._dependents

  def dependencies(self):
    return self._dependencies

  def cyclic_dependencies(self):
    return self._cyclic_dependencies

  def dependents_of(self, node):
    return self._dependents[node]

  def dependencies_of(self, node):
    return self._dependencies[node]

  def cyclic_dependencies_of(self, node):
    return self._cyclic_dependencies[node]

  def invalidate(self, predicate=None):
    """Invalidate nodes and their subgraph of dependents given a predicate.

    :param func predicate: A predicate that matches Node objects for all nodes in the graph.
    """
    def _delete_node(node):
      del self._node_results[node]
      del self._dependents[node]
      del self._dependencies[node]
      self._cyclic_dependencies.pop(node, None)

    def _sever_root_dependents(roots):
      for root in roots:
        for associated in self._dependencies[root]:
          self._dependents[associated].discard(root)

    def all_predicate(_): return True
    predicate = predicate or all_predicate

    invalidated_roots = list(node for node in self._node_results.keys() if predicate(node))
    invalidated_nodes = list(node for (node, _), _ in self.walk(roots=invalidated_roots,
                                                                predicate=all_predicate,
                                                                dependents=True))

    # Sever dependee->dependent relationships in the graph for all given invalidated roots. This
    # only applies to the outer-most invalidated root nodes due to possible references from non-
    # invalidated nodes via dependents.
    for root in invalidated_roots:
      _sever_root_dependents(invalidated_roots)

    # Delete all nodes based on a backwards walk of the graph from all matching invalidated roots.
    for node in invalidated_nodes:
      _delete_node(node)

    return len(invalidated_nodes)

  def walk(self, roots, predicate=None, dependents=False):
    """Yields Nodes depth-first in pre-order, starting from the given roots.

    Each node entry is actually a tuple of (Node, State), and each yielded value is
    a tuple of (node_entry, dep_node_entries).

    The given predicate is applied to entries, and eliminates the subgraphs represented by nodes
    that don't match it. The default predicate eliminates all `Noop` subgraphs.

    TODO: Not very many consumers actually need the dependency list here: should drop it and
    allow them to request it specifically.
    """
    def _default_walk_predicate(entry):
      node, state = entry
      return type(state) is not Noop
    predicate = predicate or _default_walk_predicate

    def _filtered_entries(nodes):
      all_entries = [(n, self.state(n)) for n in nodes]
      if not predicate:
        return all_entries
      return [entry for entry in all_entries if predicate(entry)]

    walked = set()
    adjacencies = self.dependents_of if dependents else self.dependencies_of
    def _walk(entries):
      for entry in entries:
        node, state = entry
        if node in walked:
          continue
        walked.add(node)

        deps = _filtered_entries(adjacencies(node))
        yield (entry, deps)
        for e in _walk(deps):
          yield e

    for entry in _walk(_filtered_entries(roots)):
      yield entry


class ExecutionRequest(datatype('ExecutionRequest', ['roots'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Root Nodes for this request.
  :type roots: list of :class:`pants.engine.exp.nodes.Node`
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


class NodeBuilder(Closable):
  """Holds an index of tasks used to instantiate TaskNodes."""

  @classmethod
  def create(cls, tasks):
    """Indexes tasks by their output type."""
    serializable_tasks = defaultdict(set)
    for output_type, input_selects, task in tasks:
      serializable_tasks[output_type].add((task, tuple(input_selects)))
    return cls(serializable_tasks)

  def __init__(self, tasks):
    self._tasks = tasks

  def gen_nodes(self, subject, product, variants):
    # Native filesystem operations.
    if FilesystemNode.is_filesystem_product(product):
      yield FilesystemNode(subject, product, variants)

    # Tasks.
    for task, anded_clause in self._tasks[product]:
      yield TaskNode(subject, product, variants, task, anded_clause)

  def select_node(self, selector, subject, variants):
    """Constructs a Node for the given Selector and the given Subject/Variants.

    This method is decoupled from Selector classes in order to allow the `selector` package to not
    need a dependency on the `nodes` package.
    """
    selector_type = type(selector)
    if selector_type is Select:
      return SelectNode(subject, selector.product, variants, None)
    elif selector_type is SelectVariant:
      return SelectNode(subject, selector.product, variants, selector.variant_key)
    elif selector_type is SelectDependencies:
      return DependenciesNode(subject, selector.product, variants, selector.deps_product, selector.field)
    elif selector_type is SelectProjection:
      return ProjectionNode(subject, selector.product, variants, selector.projected_subject, selector.fields, selector.input_product)
    elif selector_type is SelectLiteral:
      # NB: Intentionally ignores subject parameter to provide a literal subject.
      return SelectNode(selector.subject, selector.product, variants, None)
    else:
      raise ValueError('Unrecognized Selector type "{}" for: {}'.format(selector_type, selector))


class StepRequest(datatype('Step', ['step_id', 'node', 'dependencies', 'project_tree'])):
  """Additional inputs needed to run Node.step for the given Node.

  TODO: See docs on StepResult.

  :param step_id: A unique id for the step, to ease comparison.
  :param node: The Node instance that will run.
  :param dependencies: The declared dependencies of the Node from previous Waiting steps.
  :param project_tree: A FileSystemProjectTree instance.
  """

  def __call__(self, node_builder):

    """Called by the Engine in order to execute this Step."""
    step_context = StepContext(node_builder, self.project_tree)
    state = self.node.step(self.dependencies, step_context)
    return (StepResult(state,))

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

  def __init__(self, goals, tasks, storage, project_tree, graph_lock=None, graph_validator=None):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param graph_lock: A re-entrant lock to use for guarding access to the internal ProductGraph
                       instance. Defaults to creating a new threading.RLock().
    """
    self._products_by_goal = goals
    self._tasks = tasks
    self._project_tree = project_tree
    self._node_builder = NodeBuilder.create(self._tasks)

    self._graph_validator = graph_validator
    self._product_graph = ProductGraph()
    self._product_graph_lock = graph_lock or threading.RLock()
    self._step_id = 0

  def _create_step(self, node):
    """Creates a Step and Promise with the currently available dependencies of the given Node.

    If the dependencies of a Node are not available, returns None.

    TODO: Content addressing node and its dependencies should only happen if node is cacheable
      or in a multi-process environment.
    """
    Node.validate_node(node)

    # See whether all of the dependencies for the node are available.
    deps = dict()
    for dep in self._product_graph.dependencies_of(node):
      state = self._product_graph.state(dep)
      if state is None:
        return None
      deps[dep] = state
    # Additionally, include Noops for any dependencies that were cyclic.
    for dep in self._product_graph.cyclic_dependencies_of(node):
      noop_state = Noop('Dep from {} to {} would cause a cycle.'.format(node, dep))
      deps[dep] = noop_state

    # Ready.
    self._step_id += 1
    return (StepRequest(self._step_id, node, deps, self._project_tree), Promise())

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
      :class:`pants.engine.exp.fs.PathGlobs` objects.
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
      :class:`pants.engine.exp.fs.PathGlobs` objects.
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
            yield DependenciesNode(subject, product, None, Paths, None)
          else:
            raise ValueError('Unsupported root subject type: {}'.format(subject))

    return ExecutionRequest(tuple(roots()))

  @property
  def product_graph(self):
    return self._product_graph

  def root_entries(self, execution_request):
    """Returns the roots for the given ExecutionRequest as a dict from Node to State."""
    with self._product_graph_lock:
      return {root: self._product_graph.state(root) for root in execution_request.roots}

  def _complete_step(self, node, step_result):
    """Given a StepResult for the given Node, complete the step."""
    result = step_result.state
    # Update the Node's state in the graph.
    self._product_graph.update_state(node, result)

  def invalidate(self, predicate=None):
    """Calls `ProductGraph.invalidate()` against an internal ProductGraph instance under
    protection of a scheduler-level lock."""
    with self._product_graph_lock:
      return self._product_graph.invalidate(predicate)

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """
    # A dict from Node to a possibly executing Step. Only one Step exists for a Node at a time.
    outstanding = {}
    # Nodes that might need to have Steps created (after any outstanding Step returns).
    candidates = set(execution_request.roots)

    with self._product_graph_lock:
      # Yield nodes that are ready, and then compute new ones.
      scheduling_iterations = 0
      while True:
        # Create Steps for candidates that are ready to run, and not already running.
        ready = dict()
        for candidate_node in list(candidates):
          if candidate_node in outstanding:
            # Node is still a candidate, but is currently running.
            continue
          if self._product_graph.is_complete(candidate_node):
            # Node has already completed.
            candidates.discard(candidate_node)
            continue
          # Create a step if all dependencies are available; otherwise, can assume they are
          # outstanding, and will cause this Node to become a candidate again later.
          candidate_step = self._create_step(candidate_node)
          if candidate_step is not None:
            ready[candidate_node] = candidate_step
          candidates.discard(candidate_node)

        if not ready and not outstanding:
          # Finished.
          break
        yield ready.values()
        scheduling_iterations += 1
        outstanding.update(ready)

        # Finalize completed Steps.
        for node, entry in outstanding.items()[:]:
          step, promise = entry
          if not promise.is_complete():
            continue
          # The step has completed; see whether the Node is completed.
          outstanding.pop(node)
          self._complete_step(step.node, promise.get())
          if self._product_graph.is_complete(step.node):
            # The Node is completed: mark any of its dependents as candidates for Steps.
            candidates.update(d for d in self._product_graph.dependents_of(step.node))
          else:
            # Waiting on dependencies.
            incomplete_deps = [d for d in self._product_graph.dependencies_of(step.node)
                               if not self._product_graph.is_complete(d)]
            if incomplete_deps:
              # Mark incomplete deps as candidates for Steps.
              candidates.update(incomplete_deps)
            else:
              # All deps are already completed: mark this Node as a candidate for another step.
              candidates.add(step.node)

      print('executed {} nodes in {} scheduling iterations. '
            'there have been {} total steps for {} total nodes.'.format(
              sum(1 for _ in self._product_graph.walk(execution_request.roots)),
              scheduling_iterations,
              self._step_id,
              len(self._product_graph.dependencies())),
            file=sys.stderr)

      if self._graph_validator is not None:
        self._graph_validator.validate(self._product_graph)
