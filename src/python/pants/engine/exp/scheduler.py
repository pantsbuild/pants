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
from collections import defaultdict, namedtuple

import six
from twitter.common.collections import OrderedSet

from pants.build_graph.address import Address
from pants.engine.exp.addressable import extract_config_selector
from pants.engine.exp.configuration import StructWithDeps
from pants.engine.exp.objects import Serializable
from pants.engine.exp.products import Products, lift_native_product
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class Select(object):
  def simplify(self, build_graph):
    """Simplifies this Select to a serializable version."""
    return self

  @abstractmethod
  def construct_node(self, subject):
    """Constructs a Node for this select and the given subject."""


class SelectSubject(namedtuple('Subject', ['product']), Select):
  """Selects the Subject provided to the constructor."""

  def construct_node(self, subject):
    return SelectNode(subject, self.product)


class SelectDependencies(namedtuple('Dependencies', ['product', 'deps_product']), Select):
  """Selects the dependencies of a product for the subject provided to the constructor."""

  def construct_node(self, subject):
    return SelectDependenciesNode(subject, self.product, self.deps_product)


class SelectAddress(namedtuple('Address', ['address', 'product']), Select):
  """Selects the Subject represented by the given Address."""

  def simplify(self, build_graph):
    """Simplifies this Select to an executable version."""
    return SelectLiteral(build_graph.resolve(self.address), self.product)

  def construct_node(self, subject):
    raise ValueError('{} must be resolved before it can be constructed.'.format(self))


class SelectLiteral(namedtuple('LiteralSubject', ['subject', 'product']), Select):
  """Selects a literal Subject (other than the one applied to the selector)."""

  def node_constructor(self, subject):
    # NB: Intentionally ignores subject parameter.
    return SelectNode(self.subject, product)


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


class State(Serializable):
  @classmethod
  def raise_unrecognized(cls, state):
    raise ValueError('Unrecognized Node State: {}'.format(state))


class Return(namedtuple('Return', ['value']), State):
  pass


class Throw(namedtuple('Throw', ['exception']), State):
  pass


class Waiting(namedtuple('Waiting', ['dependencies']), State):
  """Indicates that a Node is waiting for some/all of the dependencies to become available.

  Some Nodes will return different dependency Nodes based on where they are in their lifecycle.
  """
  pass


class Node(Serializable):
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


class SelectNode(namedtuple('Select', ['subject', 'product']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, and so it acts like an OR.
  """

  def _dependencies(self, node_builder):
    """Returns a sequence of potential source Nodes for this Select."""
    # Look for native sources.
    yield NativeNode(self.subject, self.product)
    # And for Tasks.
    for task_node in node_builder.task_nodes(self.subject, self.product):
      yield task_node

  def step(self, dependency_states, node_builder):
    # If there are any Return Nodes, return the first.
    print('stepping {} with {}'.format(self, dependency_states))
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
      return Throw(ValueError('No source of {}, {}'.format(self.subject, self.product)))


class SelectDependenciesNode(namedtuple('SelectDependencies', ['subject', 'product', 'dep_product']), Node):
  """A Node that selects products for the dependencies of a product.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  of dep_products' dependencies.
  """

  def _dep_product_node(self):
    return SelectNode(self.subject, self.dep_product)

  def step(self, dependency_states, node_builder):
    dep_product_state = dependency_states.get(self._dep_product_node(), None)
    if dep_product_state is None or type(dep_product_state) == Waiting:
      # Wait for the product which hosts the dependency list we need.
      return Waiting([self._dep_product_node()])
    elif type(dep_product_state) == Throw:
      msg = 'Could not compute {}, {} to determine dependencies.'.format(subject, dep_product)
      return Throw(ValueError(msg))
    elif type(dep_product_state) == Return:
      # The product and its dependency list are available.
      dependencies = [SelectNode(d, product) for d in dep_product_state.value.dependencies]
      for dependency in dependencies:
        dep_state = dependency_states.get(dependency, None)
        if dep_state is None or type(dep_state) == Waiting:
          # One of the dependencies is not yet available. Indicate that we are waiting for all
          # of them.
          return Waiting([self._dep_product_node()] + dependencies)
        elif type(dep_state) == Throw:
          msg = 'Failed to compute dependency {}'.format(dependency)
          return Throw(ValueError(msg))
        elif type(dep_state) != Return:
          raise State.raise_unrecognized(dep_state)
      # All dependencies are present! Set our value to a list of the resulting values.
      return Return([dependency_states[d].value for d in dependencies])
    else:
      State.raise_unrecognized(dep_state)


class TaskNode(namedtuple('Task', ['subject', 'product', 'func', 'clause']), Node):
  def _dependencies(self, node_builder):
    for select in self.clause:
      yield select.construct_node(self.subject)

  def step(self, dependency_states, node_builder):
    # If all dependency Nodes are Return, execute the Node.
    dep_values = []
    dependencies = list(self._dependencies(node_builder))
    for dep_key in dependencies:
      dep_state = dependency_states.get(dep_key, None)
      if dep_state is None:
        return Waiting(dependencies)
      elif type(dep_state) == Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) == Throw:
        return Throw(ValueError('Dependency {} failed.'.format(dep_key)))
      else:
        State.raise_unrecognized(dep_state)
    try:
      return Return(func(*dep_values))
    except Exception as e:
      return Throw(e)


class NativeNode(namedtuple('Native', ['subject', 'product']), Node):
  def step(self, dependency_states, node_builder):
    if type(self.subject) == self.product:
      return Return(subject)
    elif getattr(self.subject, 'configurations'):
      for configuration in self.subject.configurations:
        # TODO: returning only the first configuration of a given type. Need to define mergeability
        # for products.
        if type(configuration) == self.product:
          return Return(configuration)
    return Throw(ValueError('No native source of {} for {}'.format(self.product, self.subject)))


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
      raise ValueError('Node {} is already completed with {}'.format(node, existing_state))
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
      self._dependents[dependency].add(node)

  def dependencies(self):
    return self._dependencies

  def dependents_of(self, node):
    return self._dependents[node]

  def dependencies_of(self, node):
    return self._dependencies[node]

  def sources_for(self, subject, product, consumed_product=None):
    """Yields the set of Sources for the given subject and product (which consume the given config).

    :param subject: The subject that the product will be produced for.
    :param type product: The product type the returned planners are capable of producing.
    :param consumed_product: An optional configuration to require that a planner consumes, or None.
    :rtype: sequences of Node. instances.
    """

    def consumes_product(node):
      """Returns True if the given Node recursively consumes the given product.

      TODO: This is matching on type only, while selectors are usually implemented
      as by-name. Convert config selectors to configuration mergers.
      """
      if not consumed_product:
        return True
      for dep_node in self._adjacencies[node]:
        if dep_node.product == type(consumed_product):
          return True
        elif consumes_product(dep_node):
          return True
      return False

    key = (subject, product)
    # TODO: order N: index by subject
    for node in self._nodes:
      # Yield Sources that were recursively able to consume the configuration.
      if isinstance(node.source, ProductGraph.Node.OR):
        continue
      if node.key == key and self._is_satisfiable(node) and consumes_product(node):
        yield node.source

  def products_for(self, subject):
    """Returns a set of products that are possible to produce for the given subject."""
    products = set()
    # TODO: order N: index by subject
    for node in self._nodes:
      if node.subject == subject and self._is_satisfiable(node):
        products.add(node.product)
    return products


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

  def task_nodes(self, subject, product):
    for task, anded_clause in self._tasks[product]:
      yield TaskNode(subject, product, task, anded_clause)


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
  """A simple Promise/Future class to hand off a value between threads.

  TODO: switch to python's Future when it becomes available.
  """

  def __init__(self):
    self._success = None
    self._failure = None
    self._event = threading.Event()

  def is_complete(self):
    return self._event.is_set()

  def success(self, success):
    self._success = success
    self._event.set()

  def failure(self, exception):
    self._failure = exception
    self._event.set()

  def get(self):
    """Blocks until the resulting value is available, or raises the resulting exception."""
    self._event.wait()
    if self._failure:
      raise self._failure
    else:
      return self._success


class Step(namedtuple('Step', ['node', 'promise', 'dependencies', 'node_builder']), Serializable):

  def __call__(self):
    """Called by the Engine in order to execute this work in parallel. Threadsafe."""
    if self.promise.is_complete():
      raise ValueError('Step was attempted multiple times!: {}'.format(self))
    #try:
    self.promise.success(self.node.step(self.dependencies, self.node_builder))
    #except Exception as e:
    #  self.promise.failure(e)

  def finalize(self, product_graph):
    """Called by the Scheduler to collect the result of this Step. Not threadsafe.

    If the step is not completed, returns False.
    """
    if not self.promise.is_complete():
      print('>> step not yet complete for {}'.format(self.node))
      return False

    result = self.promise.get()
    if type(result) == Waiting:
      print('>> waiting for more inputs for {}'.format(self.node))
      product_graph.add_edges(self.node, result.dependencies)
    else:
      print('>> node is complete {}'.format(self.node))
      product_graph.complete(self.node, result)
    return True


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

  def _create_step(self, node):
    """Creates a Step with the currently available dependencies of the given Node."""
    return Step(node,
                Promise(),
                {dep: self._product_graph.state(dep)
                 for dep in self._product_graph.dependencies_of(node) if dep is not None},
                self._node_builder)

  def _create_roots(self, build_request):
    # Determine the root products and subjects based on the request.
    root_subjects = [self._graph.resolve(a) for a in build_request.addressable_roots]
    root_products = OrderedSet()
    for goal in build_request.goals:
      root_products.update(self._products_by_goal[goal])

    # Roots are products that might be possible to produce for these subjects.
    return [SelectNode(s, p) for s in root_subjects for p in root_products]

  def product_graph(self):
    return self._product_graph

  def schedule(self, build_request):
    """Yields batches of Steps until the roots specified by the request have been completed.
    
    This method should be called by exactly one thread, but the Step objects returned
    by this method are intended to be executed in multiple threads.
    """

    pg = self._product_graph

    # A list of Steps that are ready to execute for Nodes.
    self._roots.update(self._create_roots(build_request))
    ready = list(self._create_step(root) for root in self._roots if not pg.is_complete(root))

    # Yield nodes that are ready, and then compute new ones.
    while ready:
      yield ready

      candidates = set()
      next_ready = []
      # Gather completed steps.
      for step in ready:
        if step.finalize(pg):
          # This step has completed; if the Node has completed, its dependents are candidates.
          if pg.is_complete(step.node):
            # The Node is completed: mark any of its dependents as candidates for Steps.
            candidates.update(d for d in pg.dependents_of(step.node))
          else:
            # Waiting on dependencies: mark them as candidates for Steps.
            candidates.update(d for d in pg.dependencies_of(step.node))
        else:
          # Still waiting for this step to complete.
          next_ready.append(step)

      # Create Steps for Nodes which have had their dependencies changed since the previous round.
      for candidate_node in candidates:
        if not pg.is_complete(candidate_node):
          next_ready.append(self._create_step(candidate_node))

      ready = next_ready
