# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.exp.addressable import Addresses, parse_variants
from pants.engine.exp.fs import PathGlobs, Paths
from pants.engine.exp.nodes import (DependenciesNode, Node, NodeBuilder, Noop, Return, SelectNode,
                                    TaskNode, Throw, Waiting)
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

  def _set_state(self, node, state):
    existing_state = self._node_results.get(node, None)
    if existing_state is not None:
      raise ValueError('Node {} is already completed:\n  {}\n  {}'.format(node, existing_state, state))
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
    elif type(state) == Waiting:
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
    def _default_walk_predicate(entry):
      node, state = entry
      cls = type(state)
      return cls is not Noop
    predicate = predicate or _default_walk_predicate

    def _filtered_entries(nodes):
      all_entries = [(n, self.state(n)) for n in nodes]
      if not predicate:
        return all_entries
      return [entry for entry in all_entries if predicate(entry)]

    walked = set()
    def _walk(entries):
      for entry in entries:
        node, state = entry
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


class BuildRequest(datatype('BuildRequest', ['goals', 'roots'])):
  """Describes the user-requested build.

  To create a BuildRequest, see `LocalScheduler.build_request`.

  :param goals: The list of goal names supplied on the command line.
  :type goals: list of string
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


class Step(datatype('Step', ['step_id', 'node', 'subject', 'dependencies'])):
  """All inputs needed to run Node.step for the given Node.
  
  TODO: See docs on StepResult.
  
  :param step_id: A unique id for the step, to ease comparison.
  :param node: The Node instance that will run.
  :param subject: The Subject referred to by Node.subject_key.
  :param dependencies: The declared dependencies of the Node from previous Waiting steps.
  """

  def __call__(self, node_builder):
    """Called by the Engine in order to execute this Step."""
    return self.node.step(self.subject, self.dependencies)

  def __eq__(self, other):
    return type(self) == type(other) and self.step_id == other.step_id

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.step_id)

  def __repr__(self):
    return str(self)

  def __str__(self):
    return 'Step({}, {})'.format(self.step_id, self.node)


class StepResult(datatype('Step', ['state', 'introduced_subjects'])):
  """The result of running a Step, passed back to the Scheduler via the Promise class.

  TODO: For simplicity, Step and StepResult both pessimistically inline all input/output content,
  which means that a lot of excess data crosses process boundaries. To do this more efficiently,
  a multi-process setup should have local storage, and multi-round RPC should determine which
  inputs/outputs are not already present in the remote process before sending blobs.
  
  :param state: The State value returned by the Step.
  :param introduced_subjects: A Subjects instance containing any potentially new subjects
    created by the Step.
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
      node, state = entry
      return root.subject_key == node.subject_key and type(state) is Return
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
      node, state = entry
      return root.subject_key == node.subject_key
    for ((node, state), dependencies) in product_graph.walk([root], predicate=predicate):
      # Look for unsatisfied TaskNodes with at least one unsatisfied dependency.
      if type(node) is not TaskNode:
        continue
      if type(state) is not Noop:
        continue
      missing_products = {dep.product for dep, state in dependencies if type(state) == Noop}
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

  def __init__(self, goals, tasks, subjects, symbol_table_cls):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param subjects: A Subjects instance that will be used to store/retrieve subjects. Should
           already contain any "literal" subject values that the given tasks require.
    """
    self._products_by_goal = goals
    self._tasks = tasks
    self._subjects = subjects

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
      state = self._product_graph.state(dep)
      if state is None:
        return None
      deps[dep] = state
    # Additionally, include Noops for any dependencies that were cyclic.
    for dep in self._product_graph.cyclic_dependencies_of(node):
      deps[dep] = Noop('Dep from {} to {} would cause a cycle.'.format(node, dep))

    # Ready.
    subject = self._subjects.get(node.subject_key)
    self._step_id += 1
    return (Step(self._step_id, node, subject, deps, self._node_builder), Promise())

  def node_builder(self):
    """Create and return a NodeBuilder instance for this Scheduler.

    A NodeBuilder is a relatively heavyweight object (since it contains an index of all
    registered tasks), so it should be used for the execution of multiple Steps.
    """
    return NodeBuilder.create(self._tasks)

  def build_request(self, goals, subjects):
    """Create and return a BuildRequest for the given goals and subjects.

    The resulting BuildRequest object will contain keys tied to this scheduler's ProductGraph, and
    so it will not be directly usable with other scheduler instances without being re-created.

    :param goals: The list of goal names supplied on the command line.
    :type goals: list of string
    :param subjects: A list of Spec and/or PathGlobs objects.
    :type subjects: list of :class:`pants.base.specs.Spec` and/or :class:`pants.engine.exp.fs.PathGlobs`
    """

    # Determine the root Nodes for the products and subjects selected by the goals and specs.
    def roots():
      for goal_name in goals:
        product = self._products_by_goal[goal_name]
        for subject in subjects:
          if type(subject) is SingleAddress:
            subject, variants = parse_variants(Address.parse(subject.to_spec_string()))
            subject_key = self._subjects.put(subject)
            yield SelectNode(subject_key, product, variants, None)
          elif type(subject) in [SiblingAddresses, DescendantAddresses]:
            subject_key = self._subjects.put(subject)
            yield DependenciesNode(subject_key, product, None, Addresses, None)
          elif type(subject) is PathGlobs:
            subject_key = self._subjects.put(subject)
            yield DependenciesNode(subject_key, product, None, Paths, None)
          else:
            raise ValueError('Unsupported root subject type: {}'.format(subject))

    return BuildRequest(goals, tuple(roots()))

  @property
  def product_graph(self):
    return self._product_graph

  def walk_product_graph(self, build_request, predicate=None):
    """Yields Nodes depth-first in pre-order, starting from the roots for this Scheduler.

    Each node entry is actually a tuple of (Node, State), and each yielded value is
    a tuple of (node_entry, dependency_node_entries).

    The given predicate is applied to entries, and eliminates the subgraphs represented by nodes
    that don't match it. The default predicate eliminates all `Noop` subgraphs.
    """
    for entry in self._product_graph.walk(build_request.roots, predicate=predicate):
      yield entry

  def root_entries(self, build_request):
    """Returns the roots for the given BuildRequest as a dict from Node to State."""
    return {root: self._product_graph.state(root) for root in build_request.roots}

  def schedule(self, build_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """

    pg = self._product_graph

    # A dict from Node to a possibly executing Step. Only one Step exists for a Node at a time.
    outstanding = {}
    # Nodes that might need to have Steps created (after any outstanding Step returns).
    candidates = set(build_request.roots)

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
        pg.update_state(step.node, promise.get())
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
          'with {} nodes in the executed path. there are now {} unique subjects.'.format(
            len(pg.dependencies()),
            scheduling_iterations,
            self._step_id,
            sum(1 for _ in pg.walk(build_request.roots)),
            self._subjects.len()))

  def validate(self):
    """Validates the generated product graph with the configured GraphValidator."""
    self._graph_validator.validate(self._product_graph)
