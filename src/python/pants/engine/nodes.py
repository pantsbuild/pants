# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
import os
from abc import abstractmethod, abstractproperty
from os.path import dirname

from twitter.common.collections import OrderedSet

from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.addressable import parse_variants
from pants.engine.fs import (DirectoryListing, FileContent, FileDigest, ReadLink, file_content,
                             file_digest, read_link, scan_directory)
from pants.engine.selectors import Select, SelectVariant
from pants.engine.struct import HasProducts, Variants
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def _satisfied_by(t, o):
  """Pickleable type check function."""
  return t.satisfied_by(o)


class ConflictingProducersError(Exception):
  """Indicates that there was more than one source of a product for a given subject.

  TODO: This will need to be legal in order to support multiple Planners producing a
  (mergeable) Classpath for one subject, for example. see:
    https://github.com/pantsbuild/pants/issues/2526
  """

  @classmethod
  def create(cls, subject, product, matches):
    """Factory method to format the error message.

    This is provided as a workaround to http://bugs.python.org/issue17296 to make this exception
    picklable.
    """
    msgs = '\n  '.join('{}:\n    {}'.format(k, v) for k, v in matches)
    return ConflictingProducersError('More than one source of {} for {}:\n  {}'
                                     .format(product.__name__, subject, msgs))

  def __init__(self, message):
    super(ConflictingProducersError, self).__init__(message)


class State(object):
  @classmethod
  def raise_unrecognized(cls, state):
    raise ValueError('Unrecognized Node State: {}'.format(state))

  @staticmethod
  def from_components(components):
    """Given the components of a State, construct the State."""
    cls, remainder = components[0], components[1:]
    return cls._from_components(remainder)

  def to_components(self):
    """Return a flat tuple containing individual pickleable components of the State.

    TODO: Consider https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-external-objects
    for this usecase?
    """
    return (type(self),) + self._to_components()

  @classmethod
  def _from_components(cls, components):
    """Given the components of a State, construct the State.

    Default implementation assumes that `self` extends tuple.
    """
    return cls(*components)

  def _to_components(self):
    """Return all components of the State as a flat tuple.

    Default implementation assumes that `self` extends tuple.
    """
    return self


class Noop(datatype('Noop', ['format_string', 'args']), State):
  """Indicates that a Node did not have the inputs which would be needed for it to execute.

  Because Noops are very common but rarely displayed, they are formatted lazily.
  """

  @staticmethod
  def cycle(src, dst):
    return Noop('Cycle detected! Edge would cause a cycle: {} -> {}.', src, dst)

  def __new__(cls, format_string, *args):
    return super(Noop, cls).__new__(cls, format_string, args)

  @classmethod
  def _from_components(cls, components):
    return cls(components[0], *components[1])

  @property
  def msg(self):
    if self.args:
      return self.format_string.format(*self.args)
    else:
      return self.format_string

  def __str__(self):
    return 'Noop(msg={!r})'.format(self.msg)


class Return(datatype('Return', ['value']), State):
  """Indicates that a Node successfully returned a value."""

  @classmethod
  def _from_components(cls, components):
    return cls(components[0])

  def _to_components(self):
    return (self.value,)


class Throw(datatype('Throw', ['exc']), State):
  """Indicates that a Node should have been able to return a value, but failed."""


class Runnable(datatype('Runnable', ['func', 'args']), State):
  """Indicates that the Node is ready to run with the given closure.

  The return value of the Runnable will become the final state of the Node.

  Overrides _to_components and _from_components to flatten the function arguments as independent
  pickleable values.
  """

  @classmethod
  def _from_components(cls, components):
    return cls(components[0], components[1:])

  def _to_components(self):
    return (self.func,) + self.args


class Waiting(datatype('Waiting', ['dependencies']), State):
  """Indicates that a Node is waiting for some/all of the dependencies to become available.

  Some Nodes will return different dependency Nodes based on where they are in their lifecycle,
  but all returned dependencies are recorded for the lifetime of a Node.
  """

  def __new__(cls, dependencies):
    obj = super(Waiting, cls).__new__(cls, dependencies)
    if any(not isinstance(n, Node) for n in dependencies):
      raise TypeError('Included non-Node dependencies {}'.format(dependencies))
    return obj


class Node(AbstractClass):
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

  @abstractproperty
  def is_cacheable(self):
    """Whether this Node type can be cached."""

  @abstractproperty
  def is_inlineable(self):
    """Whether this Node type can have its execution inlined.

    In cases where a Node is inlined, it is executed directly in the step method of a dependent
    Node, and is not memoized or cached in any way.
    """

  @abstractmethod
  def step(self, step_context):
    """Given a StepContext returns the current State of the Node.

    The StepContext holds any computed dependencies, provides a way to construct Nodes
    that require information about installed tasks, and allows access to the filesystem.
    """


class SelectNode(datatype('SelectNode', ['subject', 'variants', 'selector']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, but fails if multiple sources produce a value. The
  'variants' field represents variant configuration that is propagated to dependencies. When
  a task needs to consume a product as configured by the variants map, it uses the SelectVariant
  selector, which introduces the 'variant' value to restrict the names of values selected by a
  SelectNode.
  """
  is_cacheable = False
  is_inlineable = True

  _variant_selector = Select(Variants)

  @property
  def variant_key(self):
    if isinstance(self.selector, SelectVariant):
      return self.selector.variant_key
    else:
      return None

  @property
  def product(self):
    return self.selector.product

  def _select_literal(self, candidate, variant_value):
    """Looks for has-a or is-a relationships between the given value and the requested product.

    Returns the resulting product value, or None if no match was made.
    """
    def items():
      # Check whether the subject is-a instance of the product.
      yield candidate
      # Else, check whether it has-a instance of the product.
      if isinstance(candidate, HasProducts):
        for subject in candidate.products:
          yield subject

    # TODO: returning only the first literal configuration of a given type/variant. Need to
    # define mergeability for products.
    for item in items():
      if not self.selector.type_constraint.satisfied_by(item):
        continue
      if variant_value and not getattr(item, 'name', None) == variant_value:
        continue
      return item
    return None

  def step(self, step_context):
    # Request default Variants for the subject, so that if there are any we can propagate
    # them to task nodes.
    variants = self.variants
    if type(self.subject) is Address and self.product is not Variants:
      dep_state = step_context.select_for(self._variant_selector, self.subject, self.variants)
      if type(dep_state) is Waiting:
        return dep_state
      elif type(dep_state) is Return:
        # A subject's variants are overridden by any dependent's requested variants, so
        # we merge them left to right here.
        variants = Variants.merge(dep_state.value.default.items(), self.variants)

    # If there is a variant_key, see whether it has been configured.
    if type(self.selector) is SelectVariant:
      variant_values = [value for key, value in variants
        if key == self.variant_key] if variants else None
      if not variant_values:
        # Select cannot be satisfied: no variant configured for this key.
        return Noop('Variant key {} was not configured in variants {}', self.variant_key, variants)
      variant_value = variant_values[0]
    else:
      variant_value = None

    # If the Subject "is a" or "has a" Product, then we're done.
    literal_value = self._select_literal(self.subject, variant_value)
    if literal_value is not None:
      return Return(literal_value)

    # Else, attempt to use a configured task to compute the value.
    dependencies = []
    matches = []
    for dep, dep_state in step_context.get_nodes_and_states_for(self.subject, self.product, variants):
      if type(dep_state) is Waiting:
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        # We computed a value: see whether we can use it.
        literal_value = self._select_literal(dep_state.value, variant_value)
        if literal_value is not None:
          matches.append((dep, literal_value))
      elif type(dep_state) is Throw:
        return dep_state
      elif type(dep_state) is Noop:
        continue
      else:
        State.raise_unrecognized(dep_state)

    # If any dependencies were unavailable, wait for them; otherwise, determine whether
    # a value was successfully selected.
    if dependencies:
      return Waiting(dependencies)
    elif len(matches) == 0:
      return Noop('No source of {}.', self)
    elif len(matches) > 1:
      # TODO: Multiple successful tasks are not currently supported. We should allow for this
      # by adding support for "mergeable" products. see:
      #   https://github.com/pantsbuild/pants/issues/2526
      return Throw(ConflictingProducersError.create(self.subject, self.product, matches))
    else:
      return Return(matches[0][1])


class DependenciesNode(datatype('DependenciesNode', ['subject', 'variants', 'selector']), Node):
  """A Node that selects the given Product for each of the items in `field` on `dep_product`.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  member of a collection named `field` on the dep_product.

  The value produced by this Node guarantees that the order of the provided values matches the
  order of declaration in the list `field` of the `dep_product`.
  """
  is_cacheable = False
  is_inlineable = True

  def __new__(cls, subject, variants, selector):
    return super(DependenciesNode, cls).__new__(cls, subject, variants,
                                                selector)

  @property
  def dep_product(self):
    return self.selector.dep_product

  @property
  def product(self):
    return self.selector.product

  @property
  def field(self):
    return self.selector.field

  def _dependency_subject_variants(self, dep_product):
    for dependency in getattr(dep_product, self.field or 'dependencies'):
      variants = self.variants
      if isinstance(dependency, Address):
        # If a subject has literal variants for particular dependencies, they win over all else.
        dependency, literal_variants = parse_variants(dependency)
        variants = Variants.merge(variants, literal_variants)
      yield dependency, variants

  def step(self, step_context):
    # Request the product we need in order to request dependencies.
    dep_product_selector = self.selector.dep_product_selector
    dep_product_state = step_context.select_for(dep_product_selector,
                                                self.subject,
                                                self.variants)
    if type(dep_product_state) in (Throw, Waiting):
      return dep_product_state
    elif type(dep_product_state) is Noop:
      return Noop('Could not compute {} to determine dependencies.', dep_product_selector)
    elif type(dep_product_state) is not Return:
      State.raise_unrecognized(dep_product_state)

    # The product and its dependency list are available.
    dep_values = []
    dependencies = []
    for dep_subject, variants in self._dependency_subject_variants(dep_product_state.value):
      if type(dep_subject) not in self.selector.field_types:
        return Throw(TypeError('Unexpected type "{}" for {}: {!r}'
                               .format(type(dep_subject), self.selector, dep_subject)))

      product_selector = self.selector.projected_product_selector
      dep_state = step_context.select_for(product_selector, subject=dep_subject, variants=variants)
      if type(dep_state) is Waiting:
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) is Noop:
        return Throw(ValueError('No source of explicit dependency {} for {}'
                                .format(product_selector, dep_subject)))
      elif type(dep_state) is Throw:
        return dep_state
      else:
        raise State.raise_unrecognized(dep_state)
    if dependencies:
      return Waiting(dependencies)
    # All dependencies are present!
    return Return(dep_values)


class ProjectionNode(datatype('ProjectionNode', ['subject', 'variants', 'selector']), Node):
  """A Node that selects the given input Product for the Subject, and then selects for a new subject.

  TODO: This is semantically very similar to DependenciesNode (which might be considered to be a
  multi-field projection for the contents of a list). Should be looking for ways to merge them.
  """
  is_cacheable = False
  is_inlineable = True

  @property
  def product(self):
    return self.selector.product

  @property
  def projected_subject(self):
    return self.selector.projected_subject

  @property
  def fields(self):
    return self.selector.fields

  @property
  def input_product(self):
    return self.selector.input_product

  def step(self, step_context):
    # Request the product we need to compute the subject.
    input_selector = self.selector.input_product_selector
    input_state = step_context.select_for(input_selector, self.subject, self.variants)
    if type(input_state) in (Throw, Waiting):
      return input_state
    elif type(input_state) is Noop:
      return Noop('Could not compute {} in order to project its fields.', input_selector)
    elif type(input_state) is not Return:
      State.raise_unrecognized(input_state)

    # The input product is available: use it to construct the new Subject.
    input_product = input_state.value
    values = [getattr(input_product, field) for field in self.fields]

    # If there was only one projected field and it is already of the correct type, project it.
    try:
      if len(values) == 1 and type(values[0]) is self.projected_subject:
        projected_subject = values[0]
      else:
        projected_subject = self.projected_subject(*values)
    except Exception as e:
      return Throw(ValueError(
        'Fields {} of {} could not be projected as {}: {}'.format(self.fields, input_product,
          self.projected_subject, e)))

    # When the output node is available, return its result.
    output_selector = self.selector.projected_product_selector
    output_state = step_context.select_for(output_selector, projected_subject, self.variants)
    if type(output_state) in (Return, Throw, Waiting):
      return output_state
    elif type(output_state) is Noop:
      return Throw(ValueError('No source of projected dependency {}'.format(output_selector)))
    else:
      raise State.raise_unrecognized(output_state)


def _run_func_and_check_type(product_type, type_check, func, *args):
  result = func(*args)
  if type_check(result):
    return result
  else:
    raise ValueError('result of {} was not a {}, instead was {}'
                     .format(func.__name__, product_type, type(result).__name__))


class TaskNode(datatype('TaskNode', ['subject', 'variants', 'rule']), Node):
  """A Node representing execution of a non-blocking python function contained by a TaskRule.

  All dependencies of the function are declared ahead of time by the `input_selectors` of the
  rule. The TaskNode will determine whether the dependencies are available before executing the
  function, and provide a satisfied argument per clause entry to the function.
  """

  is_cacheable = True
  is_inlineable = False

  @property
  def product(self):
    return self.rule.output_product_type

  @property
  def func(self):
    return self.rule.task_func

  def step(self, step_context):
    # Compute dependencies for the Node, or determine whether it is a Noop.
    dependencies = []
    dep_values = []
    for selector in self.rule.input_selectors:
      dep_state = step_context.select_for(selector, self.subject, self.variants)

      if type(dep_state) is Waiting:
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) is Noop:
        if selector.optional:
          dep_values.append(None)
        else:
          return Noop('Was missing (at least) input for {}.', selector)
      elif type(dep_state) is Throw:
        # NB: propagate thrown exception directly.
        return dep_state
      else:
        State.raise_unrecognized(dep_state)
    # If any clause was still waiting on dependencies, indicate it; else execute.
    if dependencies:
      return Waiting(dependencies)
    # Ready to run!
    return Runnable(functools.partial(_run_func_and_check_type,
                                      self.rule.output_product_type,
                                      functools.partial(_satisfied_by, self.rule.constraint),
                                      self.rule.task_func),
                    tuple(dep_values))

  def __repr__(self):
    return 'TaskNode(subject={}, variants={}, rule={}' \
      .format(self.subject, self.variants, self.rule)

  def __str__(self):
    return repr(self)


class FilesystemNode(datatype('FilesystemNode', ['subject', 'product', 'variants']), Node):
  """A native node type for filesystem operations."""

  _FS_PAIRS = {
      (DirectoryListing, Dir),
      (FileContent, File),
      (FileDigest, File),
      (ReadLink, Link),
    }

  is_cacheable = False
  is_inlineable = False

  @classmethod
  def create(cls, subject, product_type, variants):
    assert (product_type, type(subject)) in cls._FS_PAIRS
    return FilesystemNode(subject, product_type, variants)

  @classmethod
  def generate_subjects(cls, filenames):
    """Given filenames, generate a set of subjects for invalidation predicate matching."""
    for f in filenames:
      # ReadLink, FileContent, or DirectoryListing for the literal path.
      yield File(f)
      yield Link(f)
      yield Dir(f)
      # Additionally, since the FS event service does not send invalidation events
      # for the root directory, treat any changed file in the root as an invalidation
      # of the root's listing.
      if dirname(f) in ('.', ''):
        yield Dir('')

  def step(self, step_context):
    if self.product is DirectoryListing:
      return Runnable(scan_directory, (step_context.project_tree, self.subject))
    elif self.product is FileContent:
      return Runnable(file_content, (step_context.project_tree, self.subject))
    elif self.product is FileDigest:
      return Runnable(file_digest, (step_context.project_tree, self.subject))
    elif self.product is ReadLink:
      return Runnable(read_link, (step_context.project_tree, self.subject))
    else:
      # This would be caused by a mismatch between _FS_PRODUCT_TYPES and the above switch.
      raise ValueError('Mismatched input value {} for {}'.format(self.subject, self))


class StepContext(object):
  """Encapsulates external state and the details of creating Nodes.

  This avoids giving Nodes direct access to the task list or subject set.
  """

  def __init__(self, node_builder, project_tree, node_states, inline_nodes):
    self._node_builder = node_builder
    self.project_tree = project_tree
    self._node_states = dict(node_states)
    self._parents = OrderedSet()
    self._inline_nodes = inline_nodes
    self.snapshot_archive_root = os.path.join(project_tree.build_root, '.snapshots')

  def get(self, node):
    """Given a Node and computed node_states, gets the current state for the Node.

    Optionally inlines execution of inlineable dependencies if `inline_nodes=True`.
    """
    state = self._node_states.get(node, None)
    if state is not None:
      return state
    if self._inline_nodes and node.is_inlineable:
      if node in self._parents:
        return Noop.cycle(list(self._parents)[-1], node)
      self._parents.add(node)
      state = self._node_states[node] = node.step(self)
      self._parents.remove(node)
      return state
    else:
      return Waiting([node])

  def get_nodes_and_states_for(self, subject, product, variants):
    for node in self._node_builder.gen_nodes(subject, product, variants):
      state = self.get(node)
      yield node, state

  def select_for(self, selector, subject, variants):
    """Returns the state for selecting a product via the provided selector."""
    dep_node = self._node_builder.select_node(selector, subject, variants)
    return self.get(dep_node)
