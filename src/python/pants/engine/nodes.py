# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod, abstractproperty
from os.path import dirname

from twitter.common.collections import OrderedSet

from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.addressable import parse_variants
from pants.engine.fs import (DirectoryListing, FileContent, FileDigest, ReadLink, file_content,
                             file_digest, read_link, scan_directory)
from pants.engine.selectors import (Select, SelectDependencies, SelectLiteral, SelectProjection,
                                    SelectVariant)
from pants.engine.struct import HasProducts, Variants
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


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


class Noop(datatype('Noop', ['format_string', 'args']), State):
  """Indicates that a Node did not have the inputs which would be needed for it to execute.

  Because Noops are very common but rarely displayed, they are formatted lazily.
  """

  @staticmethod
  def cycle(src, dst):
    return Noop('Edge would cause a cycle: {} -> {}.', src, dst)

  def __new__(cls, format_string, *args):
    return super(Noop, cls).__new__(cls, format_string, args)

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


class Throw(datatype('Throw', ['exc']), State):
  """Indicates that a Node should have been able to return a value, but failed."""


class Waiting(datatype('Waiting', ['dependencies']), State):
  """Indicates that a Node is waiting for some/all of the dependencies to become available.

  Some Nodes will return different dependency Nodes based on where they are in their lifecycle,
  but all returned dependencies are recorded for the lifetime of a Node.
  """


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


class SelectNode(datatype('SelectNode', ['subject', 'product', 'variants', 'variant_key']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, but fails if multiple sources produce a value. The
  'variants' field represents variant configuration that is propagated to dependencies. When
  a task needs to consume a product as configured by the variants map, it uses the SelectVariant
  selector, which introduces the 'variant' value to restrict the names of values selected by a
  SelectNode.
  """
  is_cacheable = False
  is_inlineable = True

  def _variants_node(self):
    if type(self.subject) is Address and self.product is not Variants:
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
      if isinstance(candidate, HasProducts):
        for subject in candidate.products:
          yield subject

    # TODO: returning only the first literal configuration of a given type/variant. Need to
    # define mergeability for products.
    for item in items():
      if not isinstance(item, self.product):
        continue
      if variant_value and not getattr(item, 'name', None) == variant_value:
        continue
      return item
    return None

  def step(self, step_context):
    # Request default Variants for the subject, so that if there are any we can propagate
    # them to task nodes.
    variants = self.variants
    variants_node = self._variants_node()
    if variants_node:
      dep_state = step_context.get(variants_node)
      if type(dep_state) is Waiting:
        return dep_state
      elif type(dep_state) is Return:
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
        return Noop('Variant key {} was not configured in variants {}', self.variant_key, variants)
      variant_value = variant_values[0]

    # If the Subject "is a" or "has a" Product, then we're done.
    literal_value = self._select_literal(self.subject, variant_value)
    if literal_value is not None:
      return Return(literal_value)

    # Else, attempt to use a configured task to compute the value.
    dependencies = []
    matches = []
    for dep in step_context.gen_nodes(self.subject, self.product, variants):
      dep_state = step_context.get(dep)
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


class DependenciesNode(datatype('DependenciesNode', ['subject', 'product', 'variants', 'dep_product', 'field']), Node):
  """A Node that selects the given Product for each of the items in `field` on `dep_product`.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  member of a collection named `field` on the dep_product.

  The value produced by this Node guarantees that the order of the provided values matches the
  order of declaration in the list `field` of the `dep_product`.
  """
  is_cacheable = False
  is_inlineable = True

  def _dep_product_node(self):
    return SelectNode(self.subject, self.dep_product, self.variants, None)

  def _dependency_nodes(self, step_context, dep_product):
    for dependency in getattr(dep_product, self.field or 'dependencies'):
      variants = self.variants
      if isinstance(dependency, Address):
        # If a subject has literal variants for particular dependencies, they win over all else.
        dependency, literal_variants = parse_variants(dependency)
        variants = Variants.merge(variants, literal_variants)
      yield SelectNode(dependency, self.product, variants, None)

  def step(self, step_context):
    # Request the product we need in order to request dependencies.
    dep_product_node = self._dep_product_node()
    dep_product_state = step_context.get(dep_product_node)
    if type(dep_product_state) in (Throw, Waiting):
      return dep_product_state
    elif type(dep_product_state) is Noop:
      return Noop('Could not compute {} to determine dependencies.', dep_product_node)
    elif type(dep_product_state) is not Return:
      State.raise_unrecognized(dep_product_state)

    # The product and its dependency list are available.
    dep_values = []
    dependencies = []
    for dependency in self._dependency_nodes(step_context, dep_product_state.value):
      dep_state = step_context.get(dependency)
      if type(dep_state) is Waiting:
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) is Noop:
        return Throw(ValueError('No source of explicit dependency {}'.format(dependency)))
      elif type(dep_state) is Throw:
        return dep_state
      else:
        raise State.raise_unrecognized(dep_state)
    if dependencies:
      return Waiting(dependencies)
    # All dependencies are present!
    return Return(dep_values)


class ProjectionNode(datatype('ProjectionNode', ['subject', 'product', 'variants', 'projected_subject', 'fields', 'input_product']), Node):
  """A Node that selects the given input Product for the Subject, and then selects for a new subject.

  TODO: This is semantically very similar to DependenciesNode (which might be considered to be a
  multi-field projection for the contents of a list). Should be looking for ways to merge them.
  """
  is_cacheable = False
  is_inlineable = True

  def _input_node(self):
    return SelectNode(self.subject, self.input_product, self.variants, None)

  def _output_node(self, step_context, projected_subject):
    return SelectNode(projected_subject, self.product, self.variants, None)

  def step(self, step_context):
    # Request the product we need to compute the subject.
    input_node = self._input_node()
    input_state = step_context.get(input_node)
    if type(input_state) in (Throw, Waiting):
      return input_state
    elif type(input_state) is Noop:
      return Noop('Could not compute {} in order to project its fields.', input_node)
    elif type(input_state) is not Return:
      State.raise_unrecognized(input_state)

    # The input product is available: use it to construct the new Subject.
    input_product = input_state.value
    values = []
    for field in self.fields:
      values.append(getattr(input_product, field))

    # If there was only one projected field and it is already of the correct type, project it.
    try:
      if len(values) == 1 and type(values[0]) is self.projected_subject:
        projected_subject = values[0]
      else:
        projected_subject = self.projected_subject(*values)
    except Exception as e:
      return Throw(ValueError('Fields {} of {} could not be projected as {}: {}'.format(
        self.fields, input_product, self.projected_subject, e)))
    output_node = self._output_node(step_context, projected_subject)

    # When the output node is available, return its result.
    output_state = step_context.get(output_node)
    if type(output_state) in (Return, Throw, Waiting):
      return output_state
    elif type(output_state) is Noop:
      return Throw(ValueError('No source of projected dependency {}'.format(output_node)))
    else:
      raise State.raise_unrecognized(output_state)


class TaskNode(datatype('TaskNode', ['subject', 'product', 'variants', 'func', 'clause']), Node):
  """A Node representing execution of a non-blocking python function.

  All dependencies of the function are declared ahead of time in the dependency `clause` of the
  function, so the TaskNode will determine whether the dependencies are available before
  executing the function, and provides a satisfied argument per clause entry to the function.
  """

  is_cacheable = False
  is_inlineable = False

  def step(self, step_context):
    # Compute dependencies for the Node, or determine whether it is a Noop.
    dependencies = []
    dep_values = []
    for selector in self.clause:
      dep_node = step_context.select_node(selector, self.subject, self.variants)
      dep_state = step_context.get(dep_node)
      if type(dep_state) is Waiting:
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) is Noop:
        if selector.optional:
          dep_values.append(None)
        else:
          return Noop('Was missing (at least) input {}.', dep_node)
      elif type(dep_state) is Throw:
        return dep_state
      else:
        State.raise_unrecognized(dep_state)
    # If any clause was still waiting on dependencies, indicate it; else execute.
    if dependencies:
      return Waiting(dependencies)
    try:
      return Return(self.func(*dep_values))
    except Exception as e:
      return Throw(e)

  def __repr__(self):
    return 'TaskNode(subject={}, product={}, variants={}, func={}, clause={}' \
      .format(self.subject, self.product, self.variants, self.func.__name__, self.clause)

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
  def as_intrinsics(cls):
    """Returns a dict of tuple(sbj type, product type) -> functions returning a fs node for that subject product type tuple."""
    return {(subject_type, product_type): FilesystemNode.create
            for product_type, subject_type in cls._FS_PAIRS}

  @classmethod
  def create(cls, subject, product_type, variants):
    assert (product_type, type(subject)) in cls._FS_PAIRS
    return FilesystemNode(subject, product_type, variants)

  @classmethod
  def generate_subjects(cls, filenames):
    """Given filenames, generate a set of subjects for invalidation predicate matching."""
    for f in filenames:
      # ReadLink, or FileContent for the literal path.
      yield File(f)
      yield Link(f)
      # DirectoryListing for parent dirs.
      yield Dir(dirname(f))

  def step(self, step_context):
    try:
      if self.product is DirectoryListing:
        return Return(scan_directory(step_context.project_tree, self.subject))
      elif self.product is FileContent:
        return Return(file_content(step_context.project_tree, self.subject))
      elif self.product is FileDigest:
        return Return(file_digest(step_context.project_tree, self.subject))
      elif self.product is ReadLink:
        return Return(read_link(step_context.project_tree, self.subject))
      else:
        # This would be caused by a mismatch between _FS_PRODUCT_TYPES and the above switch.
        raise ValueError('Mismatched input value {} for {}'.format(self.subject, self))
    except Exception as e:
      return Throw(e)


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

  def gen_nodes(self, subject, product, variants):
    """Yields Node instances which might be able to provide a value for the given inputs."""
    return self._node_builder.gen_nodes(subject, product, variants)

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
