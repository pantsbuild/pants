# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from collections import defaultdict

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.exp.addressable import Addresses
from pants.engine.exp.fs import PathGlobs, Paths
from pants.engine.exp.nodes import (DependenciesNode, FilesystemNode, Node, Noop, Return,
                                    SelectNode, State, StepContext, TaskNode, Throw, Waiting)
from pants.engine.exp.objects import Closable
from pants.util.objects import datatype


class PartiallyConsumedInputsError(Exception):
  """No task was able to consume a particular literal product for a subject, although some tried.

  In particular, this error allows for safe composition of configuration on targets (ie,
  ThriftSources AND ThriftConfig), because if a task requires multiple inputs for a subject
  but cannot find them, a useful error is raised.

  TODO: Improve the error message in the presence of failures due to mismatched variants.
  """

  @classmethod
  def _msg(cls, inverted_symbol_table, partially_consumed_inputs):
    def name(product):
      return inverted_symbol_table[product]
    for subject, tasks_and_inputs in partially_consumed_inputs.items():
      yield '\nSome products were partially specified for `{}`:'.format(subject)
      for ((input_product, output_product), tasks) in tasks_and_inputs.items():
        yield '  To consume `{}` and produce `{}`:'.format(name(input_product), name(output_product))
        for task, additional_inputs in tasks:
          inputs_str = ' AND '.join('`{}`'.format(name(i)) for i in additional_inputs)
          yield '    {} also needed ({})'.format(task.__name__, inputs_str)

  @classmethod
  def create(cls, inverted_symbol_table, partially_consumed_inputs):
    msg = '\n'.join(cls._msg(inverted_symbol_table, partially_consumed_inputs))
    return cls(msg)


class ProductGraph(object):

  def __init__(self):
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

  def _set_state(self, node, state_key):
    existing_state_key = self._node_results.get(node, None)
    if existing_state_key is not None:
      raise ValueError('Node {} is already completed:\n  {}\n  {}'
                       .format(node, existing_state_key, state_key))
    elif state_key.type not in [Return, Throw, Noop]:
      raise ValueError('Cannot complete Node {} with state_key {}'.format(node, state_key))
    self._node_results[node] = state_key

  def is_complete(self, node):
    return node in self._node_results

  def state(self, node):
    return self._node_results.get(node, None)

  def update_state(self, node, state_key, dependencies=None):
    """Updates the Node with the given State."""
    if state_key.type in [Return, Throw, Noop]:
      self._set_state(node, state_key)
    elif state_key.type is Waiting:
      self._add_dependencies(node, dependencies)
    else:
      raise State.raise_unrecognized(state_key)

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
    Node.validate_node(node)
    if self.is_complete(node):
      raise ValueError('Node {} is already completed, and cannot be updated.'.format(node))

    # Add deps. Any deps which would cause a cycle are added to _cyclic_dependencies instead,
    # and ignored except for the purposes of Step execution.
    node_dependencies = self._dependencies[node]
    node_cyclic_dependencies = self._cyclic_dependencies[node]
    for dependency in dependencies:
      if dependency in node_dependencies:
        continue
      Node.validate_node(dependency)
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

  def walk(self, roots, predicate=None):
    """Yields Nodes depth-first in pre-order, starting from the given roots.

    Each node entry is actually a tuple of (Node, State), and each yielded value is
    a tuple of (node_entry, dependency_node_entries).

    The given predicate is applied to entries, and eliminates the subgraphs represented by nodes
    that don't match it. The default predicate eliminates all `Noop` subgraphs.

    TODO: Not very many consumers actually need the dependency list here: should drop it and
    allow them to request it specifically.
    """
    def _default_walk_predicate(entry):
      node, state_key = entry
      return state_key.type is not Noop
    predicate = predicate or _default_walk_predicate

    def _filtered_entries(nodes):
      all_entries = [(n, self.state(n)) for n in nodes]
      if not predicate:
        return all_entries
      return [entry for entry in all_entries if predicate(entry)]

    walked = set()
    def _walk(entries):
      for entry in entries:
        node, state_key = entry
        if node in walked:
          continue
        walked.add(node)

        dependencies = _filtered_entries(self.dependencies_of(node))
        yield (entry, dependencies)
        for e in _walk(dependencies):
          yield e

    for entry in _walk(_filtered_entries(roots)):
      yield entry

  def clear(self):
    """Clears all state of the ProductGraph. Exposed for testing."""
    self._dependencies.clear()
    self._dependents.clear()
    self._cyclic_dependencies.clear()
    self._node_results.clear()


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

  def gen_nodes(self, subject_key, product, variants):
    # Native filesystem operations.
    if FilesystemNode.is_filesystem_product(product):
      yield FilesystemNode(subject_key, product, variants)

    # Tasks.
    for task, anded_clause in self._tasks[product]:
      yield TaskNode(subject_key, product, variants, task, anded_clause)


class StepRequest(datatype('Step', ['step_id', 'node', 'dependencies', 'project_tree'])):
  """Additional inputs needed to run Node.step for the given Node.

  TODO: See docs on StepResult.

  :param step_id: A unique id for the step, to ease comparison.
  :param node: The Node instance that will run.
  :param subject: The Subject referred to by Node.subject_key.
  :param dependencies: The declared dependencies of the Node from previous Waiting steps.
  :param project_tree: A FileSystemProjectTree instance.
  """

  def __call__(self, node_builder, storage):
    def from_keys():
      """Translate keys into subject and states."""
      subject = storage.get(self.node.subject_key)
      dependencies = {}
      for dep, state_key in self.dependencies.items():
        # This is for the only special case: `Noop` that is introduced in `Scheduler` to
        # handle circular dependencies. Skip lookup since it is already a `State`.
        # TODO (peiyu): we should eventually get rid of this special case.
        if isinstance(state_key, Noop):
          dependencies[dep] = state_key
        else:
          dependencies[dep] = storage.get(state_key)
      return subject, dependencies

    def to_key(state):
      """Introduce a potentially new State, and returns its key and optional dependencies."""
      state_key = storage.put(state)
      dependencies = state.dependencies if type(state) is Waiting else None
      return state_key, dependencies

    """Called by the Engine in order to execute this Step."""
    step_context = StepContext(node_builder, storage, self.project_tree)

    subject, dependencies = from_keys()
    state = self.node.step(subject, dependencies, step_context)

    state_key, dependencies = to_key(state)
    return StepResult(state_key, dependencies)

  def __eq__(self, other):
    return type(self) == type(other) and self.step_id == other.step_id

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.step_id)

  def __repr__(self):
    return str(self)

  def __str__(self):
    return 'StepRequest({}, {})'.format(self.step_id, self.node)


class StepResult(datatype('Step', ['state_key', 'dependencies'])):
  """The result of running a Step, passed back to the Scheduler via the Promise class.

  :param state_key: The key of the State that is returned by the Step.
  :param dependencies: Optional dependency nodes when the type of `State` is `Waiting`.
  """


class GraphValidator(object):
  """A concrete object that implements validation of a completed product graph.

  TODO: The name "literal" here is overloaded with SelectLiteral, which is a better fit
  for the name. The values here are more "user-specified/configured" than "literal".

  TODO: If this abstraction seems useful, we should extract an interface and allow plugin
  implementers to install their own. But currently the API isn't great: in particular, it
  would be very, very helpful to be able to run validation _during_ graph execution as
  subgraphs are completing. This would limit their performance impact, and allow for better
  locality of errors.
  """

  def __init__(self, symbol_table_cls):
    self._literal_types = dict()
    for name, cls in symbol_table_cls.table().items():
      self._literal_types[cls] = name

  def _collect_consumed_inputs(self, product_graph, root):
    """Walks successful nodes under the root for its subject, and returns all products used."""
    consumed_inputs = set()
    # Walk into successful nodes for the same subject under this root.
    def predicate(entry):
      node, state_key = entry
      return root.subject_key == node.subject_key and state_key.type is Return
    # If a product was successfully selected, record it.
    for ((node, _), _) in product_graph.walk([root], predicate=predicate):
      if type(node) is SelectNode:
        consumed_inputs.add(node.product)
    return consumed_inputs

  def _collect_partially_consumed_inputs(self, product_graph, consumed_inputs, root):
    """Walks below a failed node and collects cases where additional literal products could be used.

    Returns:
      dict(subject, dict(tuple(input_product, output_product), list(tuple(task, missing_products))))
    """
    partials = defaultdict(lambda: defaultdict(list))
    # Walk all nodes for the same subject under this root.
    def predicate(entry):
      node, state_key = entry
      return root.subject_key == node.subject_key
    for ((node, state_key), dependencies) in product_graph.walk([root], predicate=predicate):
      # Look for unsatisfied TaskNodes with at least one unsatisfied dependency.
      if type(node) is not TaskNode:
        continue
      if state_key.type is not Noop:
        continue
      missing_products = {dep.product for dep, state_key in dependencies if state_key.type is Noop}
      if not missing_products:
        continue

      # If all unattainable products could have been specified as literal...
      if any(product not in self._literal_types for product in missing_products):
        continue

      # There was at least one dep successfully (recursively) satisfied via a literal.
      # TODO: this does multiple walks.
      used_literal_deps = set()
      for dep, _ in dependencies:
        for product in self._collect_consumed_inputs(product_graph, dep):
          if product in self._literal_types:
            used_literal_deps.add(product)
      if not used_literal_deps:
        continue

      # The partially consumed products were not fully consumed elsewhere.
      if not (used_literal_deps - consumed_inputs):
        continue

      # Found a partially consumed input.
      for used_literal_dep in used_literal_deps:
        partials[node.subject_key][(used_literal_dep, node.product)].append((node.func, missing_products))
    return partials

  def validate(self, product_graph):
    """Finds 'subject roots' in the product graph and invokes validation on each of them."""

    # Locate roots: those who do not have any dependents for the same subject.
    roots = set()
    for node, dependents in product_graph.dependents().items():
      if any(d.subject_key == node.subject_key for d in dependents):
        # Node had a dependent for its subject: was not a root.
        continue
      roots.add(node)

    # Raise if there were any partially consumed inputs.
    for root in roots:
      consumed = self._collect_consumed_inputs(product_graph, root)
      partials = self._collect_partially_consumed_inputs(product_graph, consumed, root)
      if partials:
        raise PartiallyConsumedInputsError.create(self._literal_types, partials)


class LocalScheduler(object):
  """A scheduler that expands a ProductGraph by executing user defined tasks."""

  def __init__(self, goals, tasks, symbol_table_cls, project_tree):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    """
    self._products_by_goal = goals
    self._tasks = tasks
    self._project_tree = project_tree
    self._node_builder = NodeBuilder.create(self._tasks)

    self._graph_validator = GraphValidator(symbol_table_cls)
    self._product_graph = ProductGraph()
    self._step_id = -1

  def _create_step(self, node):
    """Creates a Step and Promise with the currently available dependencies of the given Node.

    If the dependencies of a Node are not available, returns None.
    """
    Node.validate_node(node)

    # See whether all of the dependencies for the node are available.
    deps = dict()
    for dep in self._product_graph.dependencies_of(node):
      state_key = self._product_graph.state(dep)
      if state_key is None:
        return None
      deps[dep] = state_key
    # Additionally, include Noops for any dependencies that were cyclic.
    for dep in self._product_graph.cyclic_dependencies_of(node):
      deps[dep] = Noop('Dep from {} to {} would cause a cycle.'.format(node, dep))

    # Ready.
    self._step_id += 1
    return (StepRequest(self._step_id, node, deps, self._project_tree), Promise())

  def node_builder(self):
    """Return the NodeBuilder instance for this Scheduler.

    A NodeBuilder is a relatively heavyweight object (since it contains an index of all
    registered tasks), so it should be used for the execution of multiple Steps.
    """
    return self._node_builder

  def build_request(self, goals, subject_keys):
    """Translate the given goal names into product types, and return an ExecutionRequest.

    :param goals: The list of goal names supplied on the command line.
    :type goals: list of string
    :param subject_keys: A list of Keys that reference Spec and/or PathGlobs objects in the storage.
    :type subject_keys: list of :class:`pants.engine.exp.Key`.
    :returns: An ExecutionRequest for the given goals and subjects.
    """
    return self.execution_request([self._products_by_goal[goal_name] for goal_name in goals],
                                  subject_keys)

  def execution_request(self, products, subject_keys):
    """Create and return an ExecutionRequest for the given products and subjects.

    The resulting ExecutionRequest object will contain keys tied to this scheduler's ProductGraph, and
    so it will not be directly usable with other scheduler instances without being re-created.

    An ExecutionRequest for an Address represents exactly one product output, as does SingleAddress. But
    we differentiate between them here in order to normalize the output for all Spec objects
    as "list of product".

    :param products: A list of product types to request for the roots.
    :type products: list of types
    :param subject_keys: A list of Keys that reference Spec and/or PathGlobs objects in the storage.
    :type subject_keys: list of :class:`pants.engine.exp.Key`.
    :returns: An ExecutionRequest for the given products and subjects.
    """

    # Determine the root Nodes for the products and subjects selected by the goals and specs.
    def roots():
      for subject_key in subject_keys:
        for product in products:
          if subject_key.type is Address:
            yield SelectNode(subject_key, product, None, None)
          elif subject_key.type in [SingleAddress, SiblingAddresses, DescendantAddresses]:
            yield DependenciesNode(subject_key, product, None, Addresses, None)
          elif subject_key.type is PathGlobs:
            yield DependenciesNode(subject_key, product, None, Paths, None)
          else:
            raise ValueError('Unsupported root subject type: {}'.format(subject_key.type))

    return ExecutionRequest(tuple(roots()))

  @property
  def product_graph(self):
    return self._product_graph

  def root_entries(self, execution_request):
    """Returns the roots for the given ExecutionRequest as a dict from Node to State."""
    return {root: self._product_graph.state(root) for root in execution_request.roots}

  def _complete_step(self, node, step_result):
    """Given a StepResult for the given Node, complete the step."""
    state_key, dependencies = step_result.state_key, step_result.dependencies
    # Update the Node's state in the graph.
    self._product_graph.update_state(node, state_key, dependencies=dependencies)

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """

    pg = self._product_graph

    # A dict from Node to a possibly executing Step. Only one Step exists for a Node at a time.
    outstanding = {}
    # Nodes that might need to have Steps created (after any outstanding Step returns).
    candidates = set(execution_request.roots)

    # Yield nodes that are ready, and then compute new ones.
    scheduling_iterations = 0
    while True:
      # Create Steps for candidates that are ready to run, and not already running.
      ready = dict()
      for candidate_node in list(candidates):
        if candidate_node in outstanding:
          # Node is still a candidate, but is currently running.
          continue
        if pg.is_complete(candidate_node):
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
        if pg.is_complete(step.node):
          # The Node is completed: mark any of its dependents as candidates for Steps.
          candidates.update(d for d in pg.dependents_of(step.node))
        else:
          # Waiting on dependencies.
          incomplete_deps = [d for d in pg.dependencies_of(step.node) if not pg.is_complete(d)]
          if incomplete_deps:
            # Mark incomplete deps as candidates for Steps.
            candidates.update(incomplete_deps)
          else:
            # All deps are already completed: mark this Node as a candidate for another step.
            candidates.add(step.node)

    print('created {} total nodes in {} scheduling iterations and {} steps, '
          'with {} nodes in the executed path.'.format(
            len(pg.dependencies()),
            scheduling_iterations,
            self._step_id,
            sum(1 for _ in pg.walk(execution_request.roots))),
          file=sys.stderr)

  def validate(self):
    """Validates the generated product graph with the configured GraphValidator."""
    self._graph_validator.validate(self._product_graph)
