# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import inspect
import itertools
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


class Select(namedtuple('Select', ['selector', 'selected_product'])):

  class Subject(object):
    """Selects the Subject provided to the selector."""
    pass

  class Dependencies(namedtuple('Dependencies', ['dep_source_product'])):
    """Selects the dependencies of a product for the Subject."""
    pass

  class LiteralSubject(namedtuple('LiteralSubject', ['address'])):
    """Selects a literal Subject (other than the one applied to the selector)."""
    pass


class Subject(object):
  """The subject of a production plan."""

  @classmethod
  def as_subject(cls, item):
    """Return the given item as the primary of a subject if its not already a subject.

    :rtype: :class:`Subject`
    """
    return item if isinstance(item, Subject) else cls(primary=item)

  @classmethod
  def iter_configured_dependencies(cls, subject):
    """Return an iterator of the given subject's dependencies including any selected configurations.

    If no configuration is selected by a dependency (there is no `@[config-name]` specifier suffix),
    then `None` is returned for the paired configuration object; otherwise the `[config-name]` is
    looked for in the subject `configurations` list and returned if found or else an error is
    raised.

    :returns: An iterator over subjects dependencies as pairs of (dependency, configuration).
    :rtype: :class:`collections.Iterator` of (object, string)
    :raises: :class:`TaskPlanner.Error` if a dependency configuration was selected by subject but
             could not be found or was not unique.
    """
    for derivation in Subject.as_subject(subject).iter_derivations:
      if getattr(derivation, 'configurations', None):
        for config in derivation.configurations:
          if isinstance(config, StructWithDeps):
            for dep in config.dependencies:
              configuration = None
              if dep.address:
                config_specifier = extract_config_selector(dep.address)
                if config_specifier:
                  if not dep.configurations:
                    raise cls.Error('The dependency of {dependee} on {dependency} selects '
                                    'configuration {config} but {dependency} has no configurations.'
                                    .format(dependee=derivation,
                                            dependency=dep,
                                            config=config_specifier))
                  configuration = dep.select_configuration(config_specifier)
              yield dep, configuration

  @classmethod
  def native_products_for_subject(self, subject):
    """Return the products that are concretely present for the given subject."""
    if isinstance(subject, Target):
      # Config products.
      for configuration in subject.configurations:
        yield configuration
    else:
      # Any other type of subject is itself a product.
      yield subject

  def __init__(self, primary, alternate=None):
    """
    :param primary: The primary subject of a production plan.
    :param alternate: An alternate subject as suggested by some other plan.
    """
    self._primary = primary
    self._alternate = alternate

  @property
  def primary(self):
    """Return the primary subject."""
    return self._primary

  @property
  def iter_derivations(self):
    """Iterates over all subjects.

    The primary subject will always be returned as the 1st item from the iterator and if there is
    an alternate, it will be returned next.

    :rtype: :class:`collection.Iterator`
    """
    yield self._primary
    if self._alternate:
      yield self._alternate

  def __hash__(self):
    return hash(self._primary)

  def __eq__(self, other):
    return isinstance(other, Subject) and self._primary == other._primary

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Subject(primary={!r}, alternate={!r})'.format(self._primary, self._alternate)


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


class ProductGraph(object):
  """A DAG of product dependencies, with (Subject, Product, `source`) tuples as nodes."""

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

      Dependencies are represented as (subject, product) pairs, because a Node should not concern
      itself with how those pairs will be computed. Some Nodes will return different dependencies
      based on where they are in their lifecycle.
      """
      pass

  class Node(Serializable):
    @abstractproperty
    def subject(self):
      """The subject for this Node."""

    @abstractproperty
    def product(self):
      """The product for this Node."""

    @property
    def key(self):
      """A uniquely identifying key for this Node.
      
      Subclasses may override to include additional info.
      """
      return (self.subject, self.product, type(self))

    @abstractmethod
    def step(self, dependency_states):
      """Given a dict of the dependency States for this Node, returns the current State of the Node.
      
      After this method returns a non-Waiting state, it will never be visited again for this Node.
      """

    class SelectDependencies(namedtuple('SelectDependencies', ['subject', 'product', 'dep_product']), Node):
      """A Node that selects products for dependencies of a product.
      
      Begins by selecting the `dep_product` for the subject, and then selects the dependencies of
      `dep_product` for each of them.
      """
      @property
      def key(self):
        return super(self, SelectDependencies).key + (self.dep_product,)

      def _dep_product_key(self):
        return (subject, dep_product)

      def step(self, dependency_states):
        dep_product_state = dependency_states.get(self._dep_product_key(), None)
        if dep_product_state is None or type(dep_product_state) == State.Waiting:
          # Wait for the product which hosts the dependency list we need.
          return State.Waiting([(subject, dep_product)])
        elif type(dep_product_state) == State.Throw:
          msg = 'Could not compute {}, {} to determine dependencies.'.format(subject, dep_product)
          return State.Throw(ValueError(msg))
        elif type(dep_product_state) == State.Return:
          # The product and its dependency list are available.
          dependencies = dep_product_state.value.dependencies
          for dependency in dependencies:
            dep_state = dependency_states.get(dependency, None)
            if dep_state is None or type(dep_state) == State.Waiting:
              # One of the dependencies is not yet available. Indicate that we are waiting for all
              # of them.
              return State.Waiting([self._dep_product_key()] + dependencies)
            elif type(dep_state) == State.Throw:
              msg = 'Failed to compute dependency of {}'.format(self._dep_product_key())
              return State.Throw(ValueError(msg))
            elif type(dep_state) != State.Return:
              raise State.raise_unrecognized(dep_state)
          # All dependencies are present! Set our value to a list of the resulting values.
          return State.Return([dependency_states[d].value for d in dependencies])
        else:
          State.raise_unrecognized(dep_state)

    class Task(namedtuple('Task', ['subject', 'product', 'func', 'clause']), Node):
      @property
      def key(self):
        # NB: it's possible for the same function to have been registered with multiple clauses, so
        # both are included in the key.
        return super(self, Task).key + (func, clause)

      def step(self, dependency_states):
        # If all dependency Nodes are Return, execute the Node.
        dep_values = []
        for dep_key in self.dependencies:
          dep_state = dependency_states.get(dep_key, None)
          if dep_state is None:
            return State.Waiting(self.dependencies)
          elif type(dep_state) == Return:
            dep_values.append(dep_state.value)
          elif type(dep_state) == Failure:
            return State.Failure(ValueError('Dependency {} failed.'.format(dep_key)))
          else:
            State.raise_unrecognized(dep_state)
        try:
          return State.Return(func(*dep_values))
        except e:
          return State.Failure(e)

    class Literal(namedtuple('Native', ['subject', 'product', 'state']), Node):
      dependencies = tuple()

      def step(self, dependency_states):
        return self.state

    class OR(namedtuple('OR', ['subject', 'product', 'dependencies']), Node):
      def step(self, dependency_states):
        # If there are any Return Nodes, return the first.
        has_waiting_dep = False
        for dep_key in self.dependencies:
          dep_state = dependency_states.get(dep_key, None)
          if type(dep_state) == State.Return:
            return dep_state
          elif type(dep_state == State.Waiting):
            has_waiting_dep = True
        if has_waiting_dep:
          return State.Waiting(dependencies)
        else:
          return State.Throw(ValueError('No source of {}'.format(self.key)))

  def __init__(self):
    # A dict from Node to its computed value: if a Node hasn't been computed yet, it will not
    # be present here.
    self._node_values = dict()
    # A dict from Node to list of dependency Nodes.
    self._adjacencies = dict()

  def add_node(self, node, dependency_nodes):
    if not isinstance(node, self.Node):
      raise ValueError('{} is not a {}'.format(node, self.Node))
    if node in self._nodes:
      raise ValueError('{} is already registered as {}'.format(node, self._nodes[]))
    self._nodes[node] = tuple(Edge(Promise(), plan) for plan in dependency_plans)

  def get(self, node):
    """The Edges for the given Node, or None."""
    return self._nodes.get(node, None)

  def _node_state(self, node):
    """Returns the state of the given Node.

    `Native` nodes are either Complete or Incomplete.
    `None` nodes are always Unsatisfiable.
    `OR` nodes are satisfied if any child is satisfied.
    `Task` nodes are satisfied if all children are satisfied."""
    if isinstance(node.source, ProductGraph.Node.Empty):
      return StateUnsatisfiable
    elif isinstance(node.source, ProductGraph.Node.Native):
      return True
    # The remaining Source types depend on the makeup of their dependencies.
    satisfied_deps = (self._is_satisfiable(dep_node) for dep_node in self._adjacencies[node])
    if isinstance(node.source, ProductGraph.Node.OR):
      # Any deps satisfied?
      return any(satisfied_deps)
    elif isinstance(node.source, ProductGraph.Node.Task):
      # All deps satisfied?
      return all(satisfied_deps)
    else:
      raise ValueError('Unimplemented `Source` type: {}'.format(node.source))

  def sources_for(self, subject, product, consumed_product=None):
    """Yields the set of Sources for the given subject and product (which consume the given config).

    :param subject: The subject that the product will be produced for.
    :param type product: The product type the returned planners are capable of producing.
    :param consumed_product: An optional configuration to require that a planner consumes, or None.
    :rtype: sequences of ProductGraph.Node. instances.
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

  def edge_strings(self):
    for node, adjacencies in self._adjacencies.items():
      for dep_node in adjacencies:
        yield '{} -> {}'.format(node, dep_node)

  def __str__(self):
    return 'ProductGraph({})'.format(', '.join(self.edge_strings()))


class Planners(object):
  """A registry of task planners indexed by both product type and goal name.

  Holds a set of input product requirements for each output product, which can be used
  to validate the graph.
  """

  def __init__(self, products_by_goal, tasks):
    self._products_by_goal = products_by_goal
    self._tasks = defaultdict(set)

    # Index tasks by their output type.
    for output_type, input_type_requirements, task in tasks:
      self._tasks[output_type].add((task, tuple(input_type_requirements)))

  def products_for_goal(self, goal_name):
    """Return the set of products required for the given goal.

    :param string goal_name:
    :rtype: set of product types
    """
    return self._products_by_goal[goal_name]

  def product_graph(self, build_graph, root_subjects, root_products):
    """Bootstraps a product graph for the given root subjects and products."""
    product_graph = ProductGraph()
    for subject in root_subjects:
      for product in root_products:
        dep_sources = self._node_sources(subject, product)
        parent = None
        # If there are multiple sources of this dependency, introduce a SourceOR node.
        if len(dep_sources) > 1:
          parent = ProductGraph.Node(subject, product, ProductGraph.Node.OR())
        for dep_source in dep_sources:
          dep_node = ProductGraph.Node(subject, product, dep_source)
          self._populate_node(product_graph, build_graph, dep_node)
          if parent:
            product_graph.add_edge(parent, dep_node)
    return product_graph

  def _node_sources(self, subject, product_type):
    """Returns a sequence of sources of the given Subject/Product."""
    # Look for native sources.
    sources = []
    for product in Subject.native_products_for_subject(subject):
      if type(product) == product_type:
        sources.append(ProductGraph.Node.Native(product))
    # And for Tasks.
    for task, anded_clause in self._tasks[product_type]:
      sources.append(ProductGraph.Node.Task(task, anded_clause))
    # If no Sources were found, return Node.Empty to indicate the hole.
    return sources or [ProductGraph.Node.Empty()]

  def _select_subjects(self, build_graph, selector, subject):
    """Yields all subjects selected by the given Select for the given subject."""
    if isinstance(selector, Select.Subject):
      yield subject
    elif isinstance(selector, Select.Dependencies):
      for dep in Subject.iter_dependencies(subject, selector.configuration):
        yield dep
    elif isinstance(selector, Select.LiteralSubject):
      yield build_graph.resolve(selector.address)
    else:
      raise ValueError('Unimplemented `Select` type: {}'.format(select))

  def _expand_node(self, product_graph, build_graph, node):
    """Expands the ProductGraph to create the given Node and its children.
    
    If the Node has already been created, then this is a noop. If it does not exist,
    this may result in recursion to expand child nodes.
    """
    deps = product_graph.get(node)
    if deps is not None:
      return

    if isinstance(node.source, ProductGraph.Node.Empty):
      # Will never be satisfied.
      product_graph.add_node(node, promise)
    elif isinstance(node.source, ProductGraph.Node.Native):
      # No dependencies; satisfied immediately.
      if not promise.completed():
        promise.success(node.source.value)
    elif isinstance(node.source, ProductGraph.Node.Select):
      # If the Select has completed, apply it to produce its child nodes.
      if promise.completed():
        input_product = promise.get()

    elif isinstance(node.source, ProductGraph.Node.Task):
      # Recurse on the dependencies of the anded Select clause.
      for dep_select in node.source.clause:
        for dep_subject in self._select_subjects(build_graph, dep_select.selector, node.subject):
          dep_sources = self._node_sources(dep_subject, dep_select.product)
          parent = node
          # If there are multiple sources of this dependency, introduce a SourceOR node.
          if len(dep_sources) > 1:
            parent = ProductGraph.Node(dep_subject, dep_select.product, ProductGraph.Node.OR())
            product_graph.add_edge(node, parent)
          # Recurse to populate each dependency Node.
          for dep_source in dep_sources:
            dep_node = ProductGraph.Node(dep_subject, dep_select.product, dep_source)
            self._populate_node(product_graph, build_graph, dep_node)
            # Then link it as a dependency of this Node.
            product_graph.add_edge(parent, dep_node)
    else:
      raise ValueError('Unsupported Source type: {}'.format(node.source))


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


class ExecutionGraph(object):
  """A DAG of execution plans where edges represent data dependencies between plans."""

  def __init__(self, root_promises, product_mapper):
    """
    :param root_promises: The root promises in the graph; these represent the final products
                          requested.
    :type root_promises: :class:`collections.Iterable` of :class:`Promise`
    :param product_mapper: A registry of all plans in the execution graph that will be used to
                           traverse from one plan's promises to the plans that will fulfill them
                           when executed.
    :type product_mapper: :class:`ProductMapper`
    """
    self._root_promises = root_promises
    self._product_mapper = product_mapper

  @property
  def root_promises(self):
    """Return the root promises in the graph.

    These represent the final products requested to satisfy a build request.

    :rtype: :class:`collections.Iterable` of :class:`Promise`
    """
    return self._root_promises

  def walk(self):
    """Performs a depth first post-order walk of the graph of execution plans.

    All plans are visited exactly once.

    :returns: A tuple of the product type the plan will produce when executed and the plan itself.
    :rtype tuple of (type, :class:`Plan`)
    """
    plans = set()
    for root_promise in self._root_promises:
      for promise, plan in self._walk_plan(root_promise, plans):
        yield promise, plan

  def _walk_plan(self, promise, plans):
    plan = self._product_mapper.promised(promise)
    if plan not in plans:
      plans.add(plan)
      for pr in plan.promises:
        for pl in self._walk_plan(pr, plans):
          yield pl
      yield promise, plan


# A synthetic planner that lifts products defined directly on targets into the product
# namespace.
class NoPlanner(TaskPlanner):
  @classmethod
  def finalize_plans(cls, plans):
    return plans


class ProductMapper(object):
  """Stores the mapping from promises to the plans whose execution will satisfy them."""

  class InvalidRegistrationError(Exception):
    """Indicates registration of a plan that does not cover the expected subject."""

  def __init__(self, graph, product_graph):
    self._graph = graph
    self._product_graph = product_graph
    self._promises = {}
    self._plans_by_product_type_by_planner = defaultdict(lambda: defaultdict(OrderedSet))

  def _register_promises(self, product_type, plan, primary_subject=None, configuration=None):
    """Registers the promises the given plan will satisfy when executed.

    :param type product_type: The product type the plan will produce when executed.
    :param plan: The plan to register promises for.
    :type plan: :class:`Plan`
    :param primary_subject: An optional primary subject.  If supplied, the registered promise for
                            this subject will be returned.
    :param object configuration: An optional promised configuration.
    :returns: The promise for the primary subject of one was supplied.
    :rtype: :class:`Promise`
    :raises: :class:`ProductMapper.InvalidRegistrationError` if a primary subject was supplied but
             not a member of the given plan's subjects.
    """
    # Index by all subjects.  This allows dependencies on products from "chunking" tasks, even
    # products from tasks that act globally in the extreme.
    primary_promise = None
    for subject in plan.subjects:
      promise = Promise(product_type, subject, configuration=configuration)
      if primary_subject == subject.primary:
        primary_promise = promise
      self._promises[promise] = plan

    if primary_subject and not primary_promise:
      raise self.InvalidRegistrationError('The subject {} is not part of the final plan!: {}'
                                          .format(primary_subject, plan))
    return primary_promise

  def promised(self, promise):
    """Return the plan that was promised.

    :param promise: The promise to lookup a registered plan for.
    :type promise: :class:`Promise`
    :returns: The plan registered for the given promise; or `None`.
    :rtype: :class:`Plan`
    """
    return self._promises.get(promise)

  def promise(self, subject, product_type, configuration=None):
    """Return a promise for a product of the given `product_type` for the given `subject`.

    The subject can either be a :class:`pants.engine.exp.objects.Serializable` object or else an
    :class:`Address`, in which case the promise subject is the addressable, serializable object it
    points to.

    If a configuration is supplied, the promise is for the requested product in that configuration.

    If no production plans can be made a :class:`SchedulingError` is raised.

    :param object subject: The subject that the product type should be created for.
    :param type product_type: The type of product to promise production of for the given subject.
    :param object configuration: An optional requested configuration for the product.
    :returns: A promise to make the given product type available for subject at task execution time.
    :rtype: :class:`Promise`
    :raises: :class:`SchedulingError` if no production plans could be made.
    """
    if isinstance(subject, Address):
      subject = self._graph.resolve(subject)

    promise = Promise(product_type, subject, configuration=configuration)
    plan = self.promised(promise)
    if plan is not None:
      return promise

    plans = []
    # For all sources of the product, request it.
    for source in self._product_graph.sources_for(subject,
                                                  product_type,
                                                  consumed_product=configuration):
      if isinstance(source, ProductGraph.Node.Native):
        plans.append((NoPlanner(), Plan(func_or_task_type=lift_native_product,
                                        subjects=(subject,),
                                        subject=subject,
                                        product_type=product_type)))
      elif isinstance(source, ProductGraph.Node.Task):
        plan = source.planner.plan(self, product_type, subject, configuration=configuration)
        # TODO: remove None check... there should no longer be any planners failing.
        if plan:
          plans.append((source.planner, plan))
      else:
        raise ValueError('Unsupported source for ({}, {}): {}'.format(
          subject, product_type, source))

    # TODO: It should be legal to have multiple plans, and they should be merged.
    if len(plans) > 1:
      raise ConflictingProducersError(product_type, subject, [plan for _, plan in plans])
    elif not plans:
      raise NoProducersError(product_type, subject, configuration)

    planner, plan = plans[0]
    try:
      primary_promise = self._register_promises(product_type, plan,
                                                primary_subject=subject,
                                                configuration=configuration)
      self._plans_by_product_type_by_planner[planner][product_type].add(plan)
      return primary_promise
    except ProductMapper.InvalidRegistrationError:
      raise SchedulingError('The plan produced for {subject!r} by {planner!r} does not cover '
                            '{subject!r}:\n\t{plan!r}'.format(subject=subject,
                                                              planner=type(planner).__name__,
                                                              plan=plan))


class LocalScheduler(object):
  """A scheduler that formulates an execution graph locally."""

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

  def __init__(self, graph, planners, build_request):
    """
    :param graph: The BUILD graph build requests will execute against.
    :type graph: :class:`pants.engine.exp.graph.Graph`
    :param planners: All the task planners known to the system.
    :type planners: :class:`Planners`
    """
    self._graph = graph
    self._planners = planners
    self._build_request = build_request


    # Determine the root products and subjects based on the request and specified goals.
    root_subjects = [self._graph.resolve(a) for a in build_request.addressable_roots]
    root_products = OrderedSet()
    for goal in build_request.goals:
      root_products.update(self._planners.products_for_goal(goal))

    # Compute a ProductGraph that determines which products are possible to produce for
    # these subjects.
    product_graph = self._planners.product_graph(self._graph, root_subjects, root_products)
    #print('>>>\n{}'.format('\n'.join(product_graph.edge_strings())))
    product_mapper = ProductMapper(self._graph, product_graph)

    # Track the root promises for relevant products for each subject.
    root_promises = []
    for subject in root_subjects:
      relevant_products = root_products & set(product_graph.products_for(subject))
      for product_type in relevant_products:
        root_promises.append(product_mapper.promise(subject, product_type))
    self._root_promises = tuple(root_promises)

  def schedule(self):
    """Determines which Promises are ready to execute.
    
    Each Promise is returned with an execution Plan containing the dependencies.
    """


    # Give aggregating planners a chance to aggregate plans.
    product_mapper.aggregate_plans()

    return ExecutionGraph(root_promises, product_mapper)

  def root_promises(self):
    return self._root_promises
