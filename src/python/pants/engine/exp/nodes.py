# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty
from collections import defaultdict

from pants.build_graph.address import Address
from pants.engine.exp.addressable import parse_variants
from pants.engine.exp.targets import Target, Variants
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class ConflictingProducersError(Exception):
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
  @classmethod
  def validate_node(cls, node):
    if not isinstance(node, Node):
      raise ValueError('Value {} is not a Node.'.format(node))

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


class DependenciesNode(datatype('DependenciesNode', ['subject', 'product', 'variants', 'dep_product', 'field']), Node):
  """A Node that selects the given Product for each of the items in a `dependencies` field on this subject.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  member a collection named `field` on the dep_product.

  The value produced by this Node guarantees that the order of the provided values matches the
  order of declaration in the list `field` of the `dep_product`.
  """

  def _dep_product_node(self):
    return SelectNode(self.subject, self.dep_product, self.variants, None)

  def _dependency_nodes(self, dep_product):
    for dependency in getattr(dep_product, self.field or 'dependencies'):
      variants = self.variants
      if isinstance(dependency, Address):
        # If a subject has literal variants for particular dependencies, they win over all else.
        dependency, literal_variants = parse_variants(dependency)
        variants = Variants.merge(variants, literal_variants)
      yield SelectNode(dependency, self.product, variants, None)

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
    dependencies = list(self._dependency_nodes(dep_product_state.value))
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


class ProjectionNode(datatype('ProjectionNode', ['subject', 'product', 'variants', 'projected_subject', 'fields', 'input_product']), Node):
  """A Node that selects the given input Product for the Subject, and then selects for a new subject.

  TODO: This is semantically very similar to DependenciesNode (which might be considered to be a
  multi-field projection for the contents of a list). Should be looking for ways to merge them.
  """

  def _input_node(self):
    return SelectNode(self.subject, self.input_product, self.variants, None)

  def _output_node(self, projected_subject):
    return SelectNode(projected_subject, self.product, self.variants, None)

  def step(self, dependency_states, node_builder):
    # Request the product we need to compute the subject.
    input_node = self._input_node()
    input_state = dependency_states.get(input_node, None)
    if input_state is None or type(input_state) == Waiting:
      return Waiting([input_node])
    elif type(input_state) == Throw:
      return input_state
    elif type(input_state) == Noop:
      return Noop('Could not compute {} in order to project its fields.'.format(input_node))
    elif type(input_state) != Return:
      State.raise_unrecognized(input_state)

    # The input product is available: use it to construct the new Subject.
    input_product = input_state.value
    values = []
    for field in self.fields:
      values.append(getattr(input_product, field))

    # If there was only one projected field and it is already of the correct type, project it.
    if len(values) == 1 and type(values[0]) is self.projected_subject:
      projected_subject = values[0]
    else:
      projected_subject = self.projected_subject(*values)
    output_node = self._output_node(projected_subject)

    # When the output node is available, return its result.
    output_state = dependency_states.get(output_node, None)
    if output_state is None or type(output_state) == Waiting:
      return Waiting([input_node, output_node])
    elif type(output_state) == Noop:
      return Noop('Successfully projected, but no source of output product for {}.'.format(output_node))
    elif type(output_state) in [Throw, Return]:
      return output_state
    else:
      raise State.raise_unrecognized(output_state)


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
    # Tasks.
    for task, anded_clause in self._tasks[product]:
      # NB: we eagerly apply the Tasks' Selectors here to avoid creating Nodes which
      # are unsatisfiable.
      if any(c.construct_node(subject, variants) is None for c in anded_clause):
        continue
      yield TaskNode(subject, product, variants, task, anded_clause)
