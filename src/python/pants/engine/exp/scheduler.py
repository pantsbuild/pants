# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import inspect
import itertools
import threading
from abc import abstractmethod, abstractproperty
from collections import defaultdict

import six
from twitter.common.collections import OrderedSet

from pants.build_graph.address import Address
from pants.engine.exp.addressable import extract_variants
from pants.engine.exp.objects import Serializable, datatype
from pants.engine.exp.struct import StructWithDeps
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class Selector(object):
  def simplify(self, build_graph):
    """Simplifies this Select to a serializable version."""
    return self

  @abstractmethod
  def construct_node(self, subject, variants):
    """Constructs a Node for this Selector and the given Subject/Variants."""


class Select(datatype('Subject', ['product']), Selector):
  """Selects the given Product for the Subject provided to the constructor."""

  def construct_node(self, subject, variants):
    return SelectNode(subject, self.product, variants)


class SelectVariant(datatype('Subject', ['variant', 'product']), Selector):
  """Selects the matching Product with the variant name for the Subject provided to the constructor.

  NB: variants only work for native Products currently. Products produced by tasks would
  likely not have a useful reason to be named.
  """

  def construct_node(self, subject, variants):
    variant_values = [value for key, value in variants
                      if key == self.variant] if variants else None
    return NativeNode(subject,
                      self.product,
                      variant_values[0] if variant_values else None)


class SelectDependencies(datatype('Dependencies', ['product', 'deps_product']), Selector):
  """Selects the dependencies of a Product for the Subject provided to the constructor."""

  def construct_node(self, subject, variants):
    return SelectDependenciesNode(subject, self.product, variants, self.deps_product)


class SelectAddress(datatype('Address', ['address', 'product']), Selector):
  """Selects the Subject represented by the given Address."""

  def simplify(self, build_graph):
    """Simplifies this Select to an executable version."""
    return SelectLiteral(build_graph.resolve(self.address), self.product)

  def construct_node(self, subject, variants):
    raise ValueError('{} must be resolved before it can be constructed.'.format(self))


class SelectLiteral(datatype('LiteralSubject', ['subject', 'product']), Selector):
  """Selects a literal Subject (other than the one applied to the selector)."""

  def construct_node(self, subject, variants):
    # NB: Intentionally ignores subject parameter to provide a literal subject.
    return SelectNode(self.subject, self.product, variants)


class Variants(object):
  """Variants are key-value pairs representing uniquely identifying parameters for a Node.

  They can be imagined as a dict in terms of dupe handling, but for easier hashability they are
  stored as sorted nested tuples of key-value strings.
  """

  @classmethod
  def merge(cls, left, right):
    """Merges right over left, ensuring that the return value is a tuple of tuples, or None."""
    if not left:
      if right:
        return tuple(right)
      else:
        return None
    if not right:
      return tuple(left)
    # Merge by key, and then return sorted by key.
    merged = dict(left)
    for key, value in right:
      merged[key] = value
    return tuple(sorted(merged.items(), key=lambda x: x[0]))


class SchedulingError(Exception):
  """Indicates inability to make a scheduling promise."""


class NoProducersError(SchedulingError):
  """Indicates no planners were able to promise a product for a given subject."""

  def __init__(self, product_type, subject=None, configuration=None):
    msg = ('No plans to generate {!r}{} could be made.'
            .format(product_type.__name__,
                    ' for {!r}'.format(subject) if subject else '',
                    ' (with config {!r})' if configuration else ''))
    super(NoProducersError, self).__init__(msg)


class PartiallyConsumedInputsError(SchedulingError):
  """No planner was able to produce a plan that consumed the given input products."""

  @staticmethod
  def msg(output_product, subject, partially_consumed_products):
    yield 'While attempting to produce {} for {}, some products could not be consumed:'.format(
             output_product.__name__, subject)
    for input_product, planners in partially_consumed_products.items():
      yield '  To consume {}:'.format(input_product)
      for planner, additional_inputs in planners.items():
        inputs_str = ' OR '.join(str(i) for i in additional_inputs)
        yield '    {} needed ({})'.format(type(planner).__name__, inputs_str)

  def __init__(self, output_product, subject, partially_consumed_products):
    msg = '\n'.join(self.msg(output_product, subject, partially_consumed_products))
    super(PartiallyConsumedInputsError, self).__init__(msg)


class ConflictingProducersError(SchedulingError):
  """Indicates more than one planner was able to promise a product for a given subject.

  TODO: This will need to be legal in order to support multiple Planners producing a
  (mergeable) Classpath for one subject, for example.
  """

  def __init__(self, product_type, subject, plans):
    msg = ('Collected the following plans for generating {!r} from {!r}:\n\t{}'
            .format(product_type.__name__,
                    subject,
                    '\n\t'.join(str(p.func_or_task_type.value) for p in plans)))
    super(ConflictingProducersError, self).__init__(msg)


class State(object):
  @classmethod
  def raise_unrecognized(cls, state):
    raise ValueError('Unrecognized Node State: {}'.format(state))


class Return(datatype('Return', ['value']), State):
  """Indicates that a Node successfully returned a value."""
  pass


class Throw(datatype('Throw', ['msg']), State):
  """Indicates that a Node should have been able to return a value, but failed."""
  pass


class Waiting(datatype('Waiting', ['dependencies']), State):
  """Indicates that a Node is waiting for some/all of the dependencies to become available.

  Some Nodes will return different dependency Nodes based on where they are in their lifecycle,
  but all returned dependencies are recorded for the lifetime of a ProductGraph.
  """
  pass


class Node(object):
  @abstractproperty
  def subject(self):
    """The subject for this Node."""

  @abstractproperty
  def product(self):
    """The product for this Node."""

  @abstractmethod
  def step(self, dependency_states, node_builder):
    """Given a dict of the dependency States for this Node, returns the current State of the Node.

    The NodeBuilder parameter provides a way to construct Nodes that require information about
    installed tasks.

    After this method returns a non-Waiting state, it will never be visited again for this Node.
    """


class SelectNode(datatype('SelectNode', ['subject', 'product', 'variants']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, and (TODO: currently) acts like an OR.
  """

  def _dependencies(self, node_builder):
    """Returns a sequence of potential source Nodes for this Select."""
    # Look for native sources.
    yield NativeNode(self.subject, self.product, None)
    # And for Tasks.
    for task_node in node_builder.task_nodes(self.subject, self.product, self.variants):
      yield task_node

  def step(self, dependency_states, node_builder):
    # If there are any Return Nodes, return the first.
    has_waiting_dep = False
    dependencies = list(self._dependencies(node_builder))
    for dep in dependencies:
      dep_state = dependency_states.get(dep, None)
      if dep_state is None or type(dep_state) == Waiting:
        has_waiting_dep = True
      elif type(dep_state) == Return:
        return dep_state
    if has_waiting_dep:
      return Waiting(dependencies)
    else:
      return Throw('No source of {}, {}'.format(self.subject, self.product))


class SelectDependenciesNode(datatype('SelectDependenciesNode', ['subject', 'product', 'variants', 'dep_product']), Node):
  """A Node that selects products for the dependencies of a product.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  of dep_products' dependencies.
  """

  def _dep_product_node(self):
    return SelectNode(self.subject, self.dep_product, self.variants)

  def _product_node(self, dependency):
    variants = self.variants
    if getattr(self.subject, 'variants', None):
      # A subject's default variants are only used if a dependent has not overridden them.
      variants = Variants.merge(self.subject.variants.items(), variants)
    if dependency.address:
      # If a subject has a literal variant for particular dependencies, it wins over all else.
      variants = Variants.merge(variants, extract_variants(dependency.address))
    return SelectNode(dependency, self.product, variants)

  def step(self, dependency_states, node_builder):
    dep_product_state = dependency_states.get(self._dep_product_node(), None)
    if dep_product_state is None or type(dep_product_state) == Waiting:
      # Wait for the product which hosts the dependency list we need.
      return Waiting([self._dep_product_node()])
    elif type(dep_product_state) == Throw:
      return Throw('Could not compute {} to determine dependencies.'.format(self._dep_product_node()))
    elif type(dep_product_state) == Return:
      # The product and its dependency list are available.
      dependencies = [self._product_node(d) for d in dep_product_state.value.dependencies]
      for dependency in dependencies:
        dep_state = dependency_states.get(dependency, None)
        if dep_state is None or type(dep_state) == Waiting:
          # One of the dependencies is not yet available. Indicate that we are waiting for all
          # of them.
          return Waiting([self._dep_product_node()] + dependencies)
        elif type(dep_state) == Throw:
          return Throw('Failed to compute dependency {}'.format(dependency))
        elif type(dep_state) != Return:
          raise State.raise_unrecognized(dep_state)
      # All dependencies are present! Set our value to a list of the resulting values.
      return Return([dependency_states[d].value for d in dependencies])
    else:
      State.raise_unrecognized(dep_state)


class TaskNode(datatype('TaskNode', ['subject', 'product', 'variants', 'func', 'clause']), Node):
  def _dependencies(self, node_builder):
    for select in self.clause:
      yield select.construct_node(self.subject, self.variants)

  def step(self, dependency_states, node_builder):
    # If all dependency Nodes are Return, execute the Node.
    dep_values = []
    dependencies = list(self._dependencies(node_builder))
    for dep_key in dependencies:
      dep_state = dependency_states.get(dep_key, None)
      if dep_state is None or type(dep_state) == Waiting:
        return Waiting(dependencies)
      elif type(dep_state) == Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) == Throw:
        return Throw('Dependency {} failed.'.format(dep_key))
      else:
        State.raise_unrecognized(dep_state)
    return Return(self.func(*dep_values))


class NativeNode(datatype('NativeNode', ['subject', 'product', 'variant']), Node):
  def step(self, dependency_states, node_builder):
    def candidates():
      yield self.subject
      if getattr(self.subject, 'configurations', None):
        for configuration in self.subject.configurations:
          yield configuration

    # TODO: returning only the last configuration of a given type. Need to define
    # mergeability for products.
    for candidate in candidates():
      if type(candidate) != self.product:
        continue
      if self.variant and not getattr(candidate, 'name', None) == self.variant:
        continue
      return Return(candidate)
    return Throw('No native source of {} for {}{}'.format(
        self.product,
        self.subject,
        '(with variant {})'.format(self.variant) if self.variant else ''))


class ProductGraph(object):

  def __init__(self):
    # A dict from Node to its computed value: if a Node hasn't been computed yet, it will not
    # be present here.
    self._node_results = dict()
    # A dict from Node to list of dependency Nodes.
    self._dependencies = defaultdict(set)
    self._dependents = defaultdict(set)

  def complete(self, node, state):
    existing_state = self._node_results.get(node, None)
    if existing_state is not None:
      raise ValueError('Node {} is already completed:\n  {}\n  {}'.format(node, existing_state, state))
    elif type(state) not in [Return, Throw]:
      raise ValueError('Cannot complete Node {} with state {}'.format(node, state))
    self._node_results[node] = state

  def is_complete(self, node):
    return node in self._node_results

  def state(self, node):
    return self._node_results.get(node, None)

  def add_edges(self, node, dependencies):
    self._dependencies[node].update(dependencies)
    for dependency in dependencies:
      #self._dependencies[dependency].update([])
      self._dependents[dependency].add(node)

  def dependencies(self):
    return self._dependencies

  def dependents_of(self, node):
    return self._dependents[node]

  def dependencies_of(self, node):
    return self._dependencies[node]

  def walk(self, roots, predicate=None):
    def _default_walk_predicate(entry):
      node, state = entry
      return type(state) != Throw
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

    for node in _walk(_filtered_entries(roots)):
      yield node


class NodeBuilder(object):
  """Encapsulates the details of creating Nodes that involve user-defined functions/tasks.

  This avoids giving Nodes direct access to the build graph, task list, or product graph.
  """

  @classmethod
  def create(cls, graph, tasks):
    """Indexes tasks by their output type, and simplifies their Select clauses.

    This allows this object to carry the minimum of information when it is serialized... in
    particular, it needn't carry along the entire graph!
    """
    serializable_tasks = defaultdict(set)
    for output_type, input_selects, task in tasks:
      simplified_input_selects = tuple(select.simplify(graph) for select in input_selects)
      serializable_tasks[output_type].add((task, simplified_input_selects))
    return cls(serializable_tasks)

  def __init__(self, tasks):
    self._tasks = tasks

  def task_nodes(self, subject, product, variants):
    for task, anded_clause in self._tasks[product]:
      yield TaskNode(subject, product, variants, task, anded_clause)


class BuildRequest(object):
  """Describes the user-requested build."""

  def __init__(self, goals, addressable_roots):
    """
    :param goals: The list of goal names supplied on the command line.
    :type goals: list of string
    :param addressable_roots: The list of addresses supplied on the command line.
    :type addressable_roots: list of :class:`pants.build_graph.address.Address`
    """
    self._goals = goals
    self._addressable_roots = addressable_roots

  @property
  def goals(self):
    """Return the list of goal names supplied on the command line.

    :rtype: list of string
    """
    return self._goals

  @property
  def addressable_roots(self):
    """Return the list of addresses supplied on the command line.

    :rtype: list of :class:`pants.build_graph.address.Address`
    """
    return self._addressable_roots

  def __repr__(self):
    return ('BuildRequest(goals={!r}, addressable_roots={!r})'
            .format(self._goals, self._addressable_roots))


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


class Step(object):
  def __init__(self, step_id, node, dependencies, node_builder):
    self._step_id = step_id
    self._node = node
    self._dependencies = dependencies
    self._node_builder = node_builder

  def __call__(self):
    """Called by the Engine in order to execute this Step."""
    return self._node.step(self._dependencies, self._node_builder)

  @property
  def node(self):
    return self._node

  def finalize(self, promise, product_graph):
    """Called by the Scheduler to collect the result of this Step. Not threadsafe.

    If the step is not completed, returns False.
    """
    if not promise.is_complete():
      return False

    result = promise.get()
    if type(result) == Waiting:
      product_graph.add_edges(self._node, result.dependencies)
    else:
      product_graph.complete(self._node, result)
    return True

  def __eq__(self, other):
    return type(self) == type(other) and self._step_id == other._step_id

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self._step_id)

  def __repr__(self):
    return str(self)

  def __str__(self):
    return 'Step({}, {})'.format(self._step_id, self._node)


class LocalScheduler(object):
  """A scheduler that expands a ProductGraph locally.

  # TODO(John Sirois): Allow for subject-less (target-less) goals.  Examples are clean-all,
  # ng-killall, and buildgen.go.
  #
  # 1. If not subjects check for a special Planner subtype with a special subject-less
  #    promise method.
  # 2. Use a sentinel NO_SUBJECT, planners that care test for this, other planners that
  #    looks for Target or Jar or ... will naturally just skip it and no-op.
  #
  # Option 1 allows for failing the build if no such subtypes are amongst the goals;
  # ie: `./pants compile` would fail since there are no inputs and all compile registered
  # planners require subjects (don't implement the subtype).
  # Seems promising - but what about mixed goals and no subjects?
  #
  # What about if subjects but the planner doesn't care about them?  Is using the IvyGlobal
  # trick good enough here?  That pattern with fake Plans to aggregate could be packaged in
  # a TaskPlanner baseclass.
  """

  def __init__(self, graph, products_by_goal, tasks):
    """
    :param graph: The BUILD graph build requests will execute against.
    :type graph: :class:`pants.engine.exp.graph.Graph`
    :param products_by_goal: The products that are required for each goal name.
    :param tasks: 
    """
    self._graph = graph
    self._products_by_goal = products_by_goal
    self._node_builder = NodeBuilder.create(graph, tasks)
    self._product_graph = ProductGraph()
    self._roots = set()
    self._step_id = -1

  def _create_step(self, node):
    """Creates a Step and Promise with the currently available dependencies of the given Node."""
    self._step_id += 1
    step = Step(self._step_id,
                node,
                {dep: self._product_graph.state(dep)
                 for dep in self._product_graph.dependencies_of(node) if dep is not None},
                self._node_builder)
    return (step, Promise())

  def _create_roots(self, build_request):
    # Determine the root products and subjects based on the request.
    root_subjects = [(self._graph.resolve(a), extract_variants(a))
                     for a in build_request.addressable_roots]
    root_products = OrderedSet()
    for goal in build_request.goals:
      root_products.update(self._products_by_goal[goal])

    # Roots are products that might be possible to produce for these subjects.
    # TODO: allow specifying variants per Subject as part BuildRequest parsing.
    return [SelectNode(s, p, v) for s, v in root_subjects for p in root_products]

  def walk_product_graph(self, predicate=None):
    """Yields Nodes depth-first in pre-order, starting from the roots for this Scheduler.

    Each node entry is actually a tuple of (Node, State), and each yielded value is
    a tuple of (node_entry, dependency_node_entries).

    The given predicate is applied to entries, and eliminates the subgraphs represented by nodes
    that don't match it. The default predicate eliminates all `Throw` subgraphs.
    """
    for node in self._product_graph.walk(self._roots, predicate=predicate):
      yield node

  def root_entries(self):
    """Returns the roots for this scheduler as a dict from Node to State."""
    return {root: self._product_graph.state(root) for root in self._roots}

  def schedule(self, build_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """

    pg = self._product_graph
    self._roots.update(self._create_roots(build_request))

    # A dict from Node to a possibly executing Step. Only one Step exists for a Node at a time.
    outstanding = {}
    # Nodes that might need to have Steps created (after any outstanding Step returns).
    candidates = set(root for root in self._roots)

    # Yield nodes that are ready, and then compute new ones.
    while True:
      # Create Steps for candidates that are not already running.
      ready = dict()
      for candidate_node in list(candidates):
        if candidate_node in outstanding:
          # Node is still a candidate, but is currently running.
          continue
        if pg.is_complete(candidate_node):
          # Previous Step for the Node caused it be completed.
          candidates.discard(candidate_node)
          continue
        ready[candidate_node] = self._create_step(candidate_node)

      if not ready and not outstanding:
        # Finished.
        break
      yield ready.values()
      outstanding.update(ready)

      # Finalize completed Steps.
      for node, entry in outstanding.items()[:]:
        step, promise = entry
        if not step.finalize(promise, pg):
          # Still executing.
          continue
        # This step has completed; if the Node has completed, its dependents are candidates.
        outstanding.pop(node)
        if pg.is_complete(step.node):
          # The Node is completed: mark any of its dependents as candidates for Steps.
          candidates.update(d for d in pg.dependents_of(step.node))
        else:
          # Waiting on dependencies: mark them as candidates for Steps.
          candidates.update(d for d in pg.dependencies_of(step.node))
