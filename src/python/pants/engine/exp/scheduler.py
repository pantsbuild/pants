# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.build_graph.address import Address
from pants.engine.exp.addressable import StructAddress, parse_variants
from pants.engine.exp.struct import Struct
from pants.engine.exp.targets import Target, Variants
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Selector(AbstractClass):
  @abstractproperty
  def optional(self):
    """Return true if this Selector is optional. It may result in a `None` match."""

  @abstractmethod
  def construct_node(self, subject, variants):
    """Constructs a Node for this Selector and the given Subject/Variants.

    May return None if the Selector can be known statically to not be satisfiable for the inputs.
    """


class Select(datatype('Subject', ['product', 'optional']), Selector):
  """Selects the given Product for the Subject provided to the constructor.

  If optional=True and no matching product can be produced, will return None.
  """

  def __new__(self, product, optional=False):
    return super(Select, self).__new__(self, product, optional)

  def construct_node(self, subject, variants):
    return SelectNode(subject, self.product, variants, None)


class SelectVariant(datatype('Variant', ['product', 'variant_key']), Selector):
  """Selects the matching Product and variant name for the Subject provided to the constructor.

  For example: a SelectVariant with a variant_key of "thrift" and a product of type ApacheThrift
  will only match when a consumer passes a variant value for "thrift" that matches the name of an
  ApacheThrift value.
  """
  optional = False

  def construct_node(self, subject, variants):
    return SelectNode(subject, self.product, variants, self.variant_key)


class SelectDependencies(datatype('Dependencies', ['product', 'deps_product']), Selector):
  """Selects the dependencies of a Product for the Subject provided to the constructor.

  The dependencies declared on `deps_product` will be provided to the requesting task
  in the order they were declared.
  """
  optional = False

  def construct_node(self, subject, variants):
    return DependenciesNode(subject, self.product, variants, self.deps_product)


class SelectProjection(datatype('Projection', ['product', 'projected_product', 'field', 'input_product']), Selector):
  """Selects a field of the given Subject to produce a Subject, Product dependency from.

  Projecting an input allows for deduplication in the graph, where multiple Subjects
  resolve to a single backing Subject instead.
  """
  optional = False

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
  optional = False

  def construct_node(self, subject, variants):
    # NB: Intentionally ignores subject parameter to provide a literal subject.
    return SelectNode(self.subject, self.product, variants, None)


class SchedulingError(Exception):
  """Indicates inability to make a scheduling promise."""


class PartiallyConsumedInputsError(SchedulingError):
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


class ConflictingProducersError(SchedulingError):
  """Indicates that there was more than one source of a product for a given subject.

  TODO: This will need to be legal in order to support multiple Planners producing a
  (mergeable) Classpath for one subject, for example. see:
    https://github.com/pantsbuild/pants/issues/2526
  """

  def __init__(self, subject, product, matches):
    msgs = '\n  '.join('{}: {}'.format(k, v) for k, v in matches.items())
    msg = 'More than one source of {} for {}:\n  {}'.format(product.__name__, subject, msgs)
    super(ConflictingProducersError, self).__init__(msg)


class State(object):
  @classmethod
  def raise_unrecognized(cls, state):
    raise ValueError('Unrecognized Node State: {}'.format(state))


class Noop(datatype('Noop', ['msg']), State):
  """Indicates that a Node did not have the inputs which would be needed for it to execute."""
  pass


class Return(datatype('Return', ['value']), State):
  """Indicates that a Node successfully returned a value."""
  pass


class Throw(datatype('Throw', ['exc']), State):
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


class SelectNode(datatype('SelectNode', ['subject', 'product', 'variants', 'variant_key']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, but fails if multiple sources produce a value. The
  'variants' field represents variant configuration that is propagated to dependencies. When
  a task needs to consume a product as configured by the variants map, it uses the SelectVariant
  selector, which introduces the 'variant' value to restrict the names of values selected by a
  SelectNode.
  """

  def _variants_node(self):
    if self.product != Variants:
      return SelectNode(self.subject, Variants, self.variants, None)
    return None

  def _select_literal(self, candidate, variant_value):
    """Looks for has-a or is-a relationships between the given value and the requested product.

    Returns the resulting product value, or None if no match was made.
    """
    def items():
      # Check whether the subject is-a instance of the product.
      yield candidate
      # Else, check whether it has-a instance of the product.
      if isinstance(candidate, Target):
        for configuration in candidate.configurations:
          yield configuration

    # TODO: returning only the first literal configuration of a given type/variant. Need to
    # define mergeability for products.
    for item in items():
      if not isinstance(item, self.product):
        continue
      if variant_value and not getattr(item, 'name', None) == variant_value:
        continue
      return item
    return None

  def step(self, dependency_states, node_builder):
    # Request default Variants for the subject, so that if there are any we can propagate
    # them to task nodes.
    variants = self.variants
    variants_node = self._variants_node()
    if variants_node:
      dep_state = dependency_states.get(variants_node, None)
      if dep_state is None or type(dep_state) == Waiting:
        return Waiting([variants_node])
      elif type(dep_state) == Return:
        # A subject's variants are overridden by any dependent's requested variants, so
        # we merge them left to right here.
        variants = Variants.merge(dep_state.value.default.items(), variants)

    # If there is a variant_key, see whether it has been configured.
    variant_value = None
    if self.variant_key:
      variant_values = [value for key, value in variants
                        if key == self.variant_key] if variants else None
      if not variant_values:
        # Select cannot be satisfied: no variant configured for this key.
        return Noop('Variant key {} was not configured in variants {}'.format(
          self.variant_key, variants))
      variant_value = variant_values[0]

    # If the Subject "is a" or "has a" Product, then we're done.
    literal_value = self._select_literal(self.subject, variant_value)
    if literal_value is not None:
      return Return(literal_value)

    # Else, attempt to use a configured task to compute the value.
    has_waiting_dep = False
    dependencies = list(node_builder.task_nodes(self.subject, self.product, variants))
    matches = {}
    for dep in dependencies:
      dep_state = dependency_states.get(dep, None)
      if dep_state is None or type(dep_state) == Waiting:
        has_waiting_dep = True
        continue
      elif type(dep_state) == Throw:
        return dep_state
      elif type(dep_state) == Noop:
        continue
      elif type(dep_state) != Return:
        State.raise_unrecognized(dep_state)
      # We computed a value: see whether we can use it.
      literal_value = self._select_literal(dep_state.value, variant_value)
      if literal_value is not None:
        matches[dep] = literal_value
    if has_waiting_dep:
      return Waiting(dependencies)
    elif len(matches) > 1:
      # TODO: Multiple successful tasks are not currently supported. We should allow for this
      # by adding support for "mergeable" products. see:
      #   https://github.com/pantsbuild/pants/issues/2526
      return Throw(ConflictingProducersError(self.subject, self.product, matches))
    elif len(matches) == 1:
      return Return(matches.values()[0])
    return Noop('No source of {}.'.format(self))


class DependenciesNode(datatype('DependenciesNode', ['subject', 'product', 'variants', 'dep_product']), Node):
  """A Node that selects the given Product for each of the dependencies of this subject.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  of dep_products' dependencies.

  The value produced by this Node guarantees that the order of the provided values matches the
  order of declaration in the `dependencies` list of the `dep_product`.
  """

  def _dep_product_node(self):
    return SelectNode(self.subject, self.dep_product, self.variants, None)

  def _dep_node(self, dependency):
    variants = self.variants
    if isinstance(dependency, Address):
      # If a subject has literal variants for particular dependencies, they win over all else.
      dependency, literal_variants = parse_variants(dependency)
      variants = Variants.merge(variants, literal_variants)
    return SelectNode(dependency, self.product, variants, None)

  def step(self, dependency_states, node_builder):
    # Request the product we need in order to request dependencies.
    dep_product_node = self._dep_product_node()
    dep_product_state = dependency_states.get(dep_product_node, None)
    if dep_product_state is None or type(dep_product_state) == Waiting:
      return Waiting([dep_product_node])
    elif type(dep_product_state) == Throw:
      return dep_product_state
    elif type(dep_product_state) == Noop:
      return Noop('Could not compute {} to determine dependencies.'.format(dep_product_node))
    elif type(dep_product_state) != Return:
      State.raise_unrecognized(dep_product_state)

    # The product and its dependency list are available.
    dep_product = dep_product_state.value
    dependencies = [self._dep_node(d) for d in dep_product.dependencies]
    for dependency in dependencies:
      dep_state = dependency_states.get(dependency, None)
      if dep_state is None or type(dep_state) == Waiting:
        # One of the dependencies is not yet available. Indicate that we are waiting for all
        # of them.
        return Waiting([dep_product_node] + dependencies)
      elif type(dep_state) == Throw:
        return dep_state
      elif type(dep_state) == Noop:
        return Throw(ValueError('No source of explicit dependency {}'.format(dependency)))
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
        return Noop('Dependency {} is not satisfiable.'.format(select))
      dependencies.append(dep)

    # If all dependency Nodes are Return, execute the Node.
    for dep_select, dep_key in zip(self.clause, dependencies):
      dep_state = dependency_states.get(dep_key, None)
      if dep_state is None or type(dep_state) == Waiting:
        return Waiting(dependencies)
      elif type(dep_state) == Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) == Noop:
        if dep_select.optional:
          dep_values.append(None)
        else:
          return Noop('Was missing (at least) input {}.'.format(dep_key))
      elif type(dep_state) == Throw:
        return dep_state
      else:
        State.raise_unrecognized(dep_state)
    try:
      return Return(self.func(*dep_values))
    except Exception as e:
      return Throw(e)


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
    if type(state) in [Return, Throw, Noop]:
      self._set_state(node, state)
    elif type(state) == Waiting:
      self._add_dependencies(node, state.dependencies)
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
    a cycle, then the _source_ Node is marked as a Noop with an error indicating the
    cycle path, and the dependencies are not introduced.
    """
    self.validate_node(node)
    if self.is_complete(node):
      raise ValueError('Node {} is already completed, and cannot be updated.'.format(node))

    # Add deps. Any deps which would cause a cycle are added to _cyclic_dependencies instead,
    # and ignored except for the purposes of Step execution.
    for dependency in dependencies:
      if dependency in self._dependencies[node]:
        continue
      self.validate_node(dependency)
      cycle_path = self._detect_cycle(node, dependency)
      if cycle_path:
        self._cyclic_dependencies[node].add(dependency)
      else:
        self._dependencies[node].add(dependency)
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


class NodeBuilder(object):
  """Encapsulates the details of creating Nodes that involve user-defined functions/tasks.

  This avoids giving Nodes direct access to the task list or product graph.
  """

  @classmethod
  def create(cls, tasks, symbol_table_cls):
    """Indexes tasks by their output type."""
    serializable_tasks = defaultdict(set)
    for output_type, input_selects, task in tasks:
      serializable_tasks[output_type].add((task, tuple(input_selects)))
    literal_products = set(symbol_table_cls.table().values())
    return cls(serializable_tasks, literal_products)

  def __init__(self, tasks, literal_products):
    self._tasks = tasks
    self._literal_products = literal_products

  def task_nodes(self, subject, product, variants):
    # Tasks.
    for task, anded_clause in self._tasks[product]:
      yield TaskNode(subject, product, variants, task, anded_clause)
    # An Address that might be resolved as a literal value from a build file.
    # TODO: This defines a special case for Addresses by recognizing that they might be-a literal
    # Product after resolution, and so it begins by attempting to resolve a Struct for
    # a subject Address. This type of cast/conversion should likely be reified.
    if isinstance(subject, Address) and product in self._literal_products:
      struct_address = StructAddress(subject.spec_path, subject.target_name)
      yield SelectNode(struct_address, Struct, None, None)


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


class GraphValidator(object):
  """A concrete object that implements validation of a completed product graph.

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
      return root.subject == node.subject and type(state) is Return
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
      return root.subject == node.subject
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
        partials[node.subject][(used_literal_dep, node.product)].append((node.func, missing_products))
    return partials

  def validate(self, product_graph):
    """Finds 'subject roots' in the product graph and invokes validation on each of them."""

    # Locate roots: those who do not have any dependents for the same subject.
    roots = set()
    for node, dependents in product_graph.dependents().items():
      if any(d.subject == node.subject for d in dependents):
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

  def __init__(self, goals, symbol_table_cls, tasks):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    """
    self._goals = goals
    self._graph_validator = GraphValidator(symbol_table_cls)
    self._node_builder = NodeBuilder.create(tasks, symbol_table_cls)
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

    # Additionally, include Noops for any dependencies that were cyclic.
    cyclic_deps = {dep: Noop('Dep from {} to {} would cause a cycle.'.format(node, dep))
                   for dep in self._product_graph.cyclic_dependencies_of(node)}
    deps.update(cyclic_deps)

    # Ready.
    self._step_id += 1
    return (Step(self._step_id, node, deps, self._node_builder), Promise())

  def _create_roots(self, build_request):
    # Determine the root products and subjects based on the request.
    root_subjects = [parse_variants(a) for a in build_request.addressable_roots]
    root_products = OrderedSet()
    for goal_name in build_request.goals:
      root_products.add(self._goals[goal_name])

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
    that don't match it. The default predicate eliminates all `Noop` subgraphs.
    """
    for entry in self._product_graph.walk(self._roots, predicate=predicate):
      yield entry

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
          'with {} nodes in the executed path.'.format(
            len(pg.dependencies()),
            scheduling_iterations,
            self._step_id,
            sum(1 for _ in pg.walk(self._roots))))

  def validate(self):
    """Validates the generated product graph with the configured GraphValidator."""
    self._graph_validator.validate(self._product_graph)
