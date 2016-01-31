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
from pants.engine.exp.addressable import parse_variants
from pants.engine.exp.objects import Serializable, datatype
from pants.engine.exp.struct import Struct
from pants.engine.exp.targets import Target
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class Selector(object):
  @abstractmethod
  def construct_node(self, subject, variants):
    """Constructs a Node for this Selector and the given Subject/Variants.

    May return None if the Selector can be known statically to not be satisfiable for the inputs.
    """


class Select(datatype('Subject', ['product']), Selector):
  """Selects the given Product for the Subject provided to the constructor."""

  def construct_node(self, subject, variants):
    return SelectNode(subject, self.product, variants, None)


class SelectVariant(datatype('Variant', ['product', 'variant_key']), Selector):
  """Selects the matching Product and variant name for the Subject provided to the constructor.

  For example: a SelectVariant with a variant_key of "thrift" and a product of type ApacheThrift
  will only match when a consumer passes a variant value for "thrift" that matches the name of an
  ApacheThrift value.
  """

  def construct_node(self, subject, variants):
    variant_values = [value for key, value in variants
                      if key == self.variant_key] if variants else None
    return SelectNode(subject,
                      self.product,
                      variants,
                      variant_values[0] if variant_values else None)


class SelectDependencies(datatype('Dependencies', ['product', 'deps_product']), Selector):
  """Selects the dependencies of a Product for the Subject provided to the constructor.

  The dependencies declared on `deps_product` will be provided to the requesting task
  in the order they were declared.
  """

  def construct_node(self, subject, variants):
    return DependenciesNode(subject, self.product, variants, self.deps_product)


class SelectProjection(datatype('Projection', ['product', 'projected_product', 'field', 'input_product']), Selector):
  """Selects a field of the given Subject to produce a Subject, Product dependency from.

  Projecting an input allows for deduplication in the graph, where multiple Subjects
  resolve to a single backing Subject instead.
  """

  def construct_node(self, subject, variants):
    # Input product type doesn't match: not satisfiable.
    if not type(subject) == self.input_product:
      return None

    # Find the field of the Subject to project.
    projected_field = getattr(subject, self.field, None)
    if projected_field is None:
      raise ValueError('Subject {} has no field {} to project.'.format(subject, self.field))
    projected_subject = self.projected_product(projected_field)
    return SelectNode(projected_subject, self.product, variants, None)


class SelectLiteral(datatype('Literal', ['subject', 'product']), Selector):
  """Selects a literal Subject (other than the one applied to the selector)."""

  def construct_node(self, subject, variants):
    # NB: Intentionally ignores subject parameter to provide a literal subject.
    return SelectNode(self.subject, self.product, variants, None)


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
    """The output product for this Node."""

  @abstractproperty
  def variants(self):
    """The variants for this Node."""

  @abstractmethod
  def step(self, dependency_states, node_builder):
    """Given a dict of the dependency States for this Node, returns the current State of the Node.

    The NodeBuilder parameter provides a way to construct Nodes that require information about
    installed tasks.

    After this method returns a non-Waiting state, it will never be visited again for this Node.
    """


class SelectNode(datatype('SelectNode', ['subject', 'product', 'variants', 'variant']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, and (TODO: currently) acts like an OR. The
  'variants' field represents variant configuration that is propagated to dependencies. When
  a task needs to consume a product as configured by the variants map, it uses the SelectVariant
  selector, which introduces the 'variant' value to restrict the names of values selected by a
  SelectNode.
  """

  def _select_literal(self, candidate):
    """Looks for has-a or is-a relationships between the given value and the requested product.

    Returns the resulting product value, or None if no match was made.
    """
    if isinstance(candidate, self.product):
      # The subject is-a instance of the product.
      return candidate
    elif isinstance(candidate, Target):
      # TODO: returning only the first configuration of a given type/variant. Need to define
      # mergeability for products.
      for configuration in candidate.configurations:
        if type(configuration) != self.product:
          continue
        if self.variant and not getattr(configuration, 'name', None) == self.variant:
          continue
        return configuration
    return None

  def _task_sources(self, node_builder):
    """Returns a sequence of potential source Nodes for this Select."""
    # Tasks.
    for task_node in node_builder.task_nodes(self.subject, self.product, self.variants):
      yield task_node
    # An Address that can be resolved into a Struct.
    # TODO: This node defines a special case for Addresses and Structs by recognizing that they
    # might be-a Product after resolution, and so it begins by attempting to resolve a Struct for
    # a subject Address. This type of cast/conversion should likely be reified.
    if isinstance(self.subject, Address) and self.product != Struct and issubclass(self.product, Struct):
      yield SelectNode(self.subject, Struct, self.variants, None)

  def step(self, dependency_states, node_builder):
    # If the Subject "is a" or "has a" Product, then we're done.
    literal_value = self._select_literal(self.subject)
    if literal_value is not None:
      return Return(literal_value)

    # Else, attempt to use a configured task to compute the value.
    has_waiting_dep = False
    dependencies = list(self._task_sources(node_builder))
    for dep in dependencies:
      dep_state = dependency_states.get(dep, None)
      if dep_state is None or type(dep_state) == Waiting:
        has_waiting_dep = True
        continue
      elif type(dep_state) == Throw:
        continue
      elif type(dep_state) != Return:
        State.raise_unrecognized(dep_state)
      # We computed a value: see whether we can use it.
      literal_value = self._select_literal(dep_state.value)
      if literal_value is not None:
        return Return(literal_value)
    if has_waiting_dep:
      return Waiting(dependencies)
    return Throw("No source of {}.".format(self))


class DependenciesNode(datatype('DependenciesNode', ['subject', 'product', 'variants', 'dep_product']), Node):
  """A Node that selects the given Product for each of the dependencies of this subject.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  of dep_products' dependencies.

  The value produced by this Node guarantees that the order of the provided values matches the
  order of declaration in the `dependencies` list of the `dep_product`.
  """

  def _dep_product_node(self):
    return SelectNode(self.subject, self.dep_product, self.variants, None)

  def _dep_node(self, variants, dependency):
    if isinstance(dependency, Address):
      # If a subject has literal variants for particular dependencies, they win over all else.
      dependency, literal_variants = parse_variants(dependency)
      variants = Variants.merge(variants, literal_variants)
    return SelectNode(dependency, self.product, variants, None)

  def step(self, dependency_states, node_builder):
    dep_product_state = dependency_states.get(self._dep_product_node(), None)
    if dep_product_state is None or type(dep_product_state) == Waiting:
      # Wait for the product which hosts the dependency list we need.
      return Waiting([self._dep_product_node()])
    elif type(dep_product_state) == Throw:
      return Throw('Could not compute {} to determine dependencies.'.format(self._dep_product_node()))
    elif type(dep_product_state) != Return:
      State.raise_unrecognized(dep_product_state)

    # The product and its dependency list are available.
    dep_product = dep_product_state.value
    variants = self.variants
    if getattr(dep_product, 'variants', None):
      # A subject's variants are overridden by the dependent's requested variants.
      variants = Variants.merge(dep_product.variants.items(), variants)
    dependencies = [self._dep_node(variants, d) for d in dep_product.dependencies]
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


class TaskNode(datatype('TaskNode', ['subject', 'product', 'variants', 'func', 'clause']), Node):

  def step(self, dependency_states, node_builder):
    # Compute dependencies.
    dep_values = []
    dependencies = []
    for select in self.clause:
      dep = select.construct_node(self.subject, self.variants)
      if dep is None:
        return Throw('Dependency {} is not satisfiable.'.format(select))
      dependencies.append(dep)

    # If all dependency Nodes are Return, execute the Node.
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


class ProductGraph(object):

  def __init__(self):
    # A dict from Node to its computed value: if a Node hasn't been computed yet, it will not
    # be present here.
    self._node_results = dict()
    # A dict from Node to list of dependency Nodes.
    self._dependencies = defaultdict(set)
    self._dependents = defaultdict(set)

  def _set_state(self, node, state):
    existing_state = self._node_results.get(node, None)
    if existing_state is not None:
      raise ValueError('Node {} is already completed:\n  {}\n  {}'.format(node, existing_state, state))
    elif type(state) not in [Return, Throw]:
      raise ValueError('Cannot complete Node {} with state {}'.format(node, state))
    self._node_results[node] = state

  @classmethod
  def validate_node(cls, node):
    if not isinstance(node, Node):
      raise ValueError('Value {} is not a Node.'.format(node))

  def is_complete(self, node):
    return node in self._node_results

  def state(self, node):
    return self._node_results.get(node, None)

  def update_state(self, node, state):
    """Updates the Node with the given State."""
    if type(state) in [Return, Throw]:
      self._set_state(node, state)
      return state
    elif type(state) == Waiting:
      self._add_dependencies(node, state.dependencies)
      return self.state(node)
    else:
      raise State.raise_unrecognized(state)

  def _detect_cycle(self, src, dest):
    """Given a src and a dest, each of which _might_ already exist in the graph, detect cycles.

    Return a path of Nodes that describe the cycle, or None.
    """
    path = OrderedSet()
    walked = set()
    def _walk(node):
      if node in path:
        return tuple(path) + (node,)
      if node in walked:
        return None
      path.add(node)
      walked.add(node)

      for dep in self.dependencies_of(node):
        found = _walk(dep)
        if found is not None:
          return found
      path.discard(node)
      return None

    # Initialize the path with src (since the edge from src->dest may not actually exist), and
    # then walk from the dest.
    path.update([src])
    return _walk(dest)

  def _add_dependencies(self, node, dependencies):
    """Adds dependency edges from the given src Node to the given dependency Nodes.

    Executes cycle detection: if adding one of the given dependencies would create
    a cycle, then the _source_ Node is marked as a Throw with an error indicating the
    cycle path, and the dependencies are not introduced.
    """
    self.validate_node(node)
    if self.is_complete(node):
      raise ValueError('Node {} is already completed, and cannot be updated.'.format(node))

    # Validate that adding these deps would not cause a cycle.
    for dependency in dependencies:
      if dependency in self._dependencies[node]:
        continue
      self.validate_node(dependency)
      cycle_path = self._detect_cycle(node, dependency)
      if cycle_path:
        # If a cycle is detected, don't introduce the dependencies, and instead fail the node.
        entries = ' ->\n  '.join(str(p) for p in cycle_path)
        self._set_state(node, Throw('Cycle detected in path:\n  {} !!'.format(entries)))
        return

    # Finally, add all deps.
    self._dependencies[node].update(dependencies)
    for dependency in dependencies:
      self._dependents[dependency].add(node)
      # 'touch' the dependencies dict for this dependency, to ensure that an entry exists.
      self._dependencies[dependency]

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

  This avoids giving Nodes direct access to the task list or product graph.
  """

  @classmethod
  def create(cls, tasks):
    """Indexes tasks by their output type."""
    serializable_tasks = defaultdict(set)
    for output_type, input_selects, task in tasks:
      serializable_tasks[output_type].add((task, tuple(input_selects)))
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
  """

  def __init__(self, products_by_goal, tasks):
    """
    :param products_by_goal: The products that are required for each goal name.
    :param tasks: 
    """
    self._products_by_goal = products_by_goal
    self._node_builder = NodeBuilder.create(tasks)
    self._product_graph = ProductGraph()
    self._roots = set()
    self._step_id = -1

  def _create_step(self, node):
    """Creates a Step and Promise with the currently available dependencies of the given Node.

    If the dependencies of a Node are not available, returns None.
    """
    ProductGraph.validate_node(node)

    # See whether all of the dependencies for the node are available.
    deps = {dep: self._product_graph.state(dep)
            for dep in self._product_graph.dependencies_of(node)}
    if any(state is None for state in deps.values()):
      return None

    # Ready.
    self._step_id += 1
    return (Step(self._step_id, node, deps, self._node_builder), Promise())

  def _create_roots(self, build_request):
    # Determine the root products and subjects based on the request.
    root_subjects = [parse_variants(a) for a in build_request.addressable_roots]
    root_products = OrderedSet()
    for goal in build_request.goals:
      root_products.update(self._products_by_goal[goal])

    # Roots are products that might be possible to produce for these subjects.
    return [SelectNode(s, p, v, None) for s, v in root_subjects for p in root_products]

  @property
  def product_graph(self):
    return self._product_graph

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
          'with {} nodes in the successful path.'.format(
            len(pg.dependencies()),
            scheduling_iterations,
            self._step_id,
            sum(1 for _ in pg.walk(self._roots))))
