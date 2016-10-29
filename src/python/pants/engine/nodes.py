# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
from abc import abstractmethod, abstractproperty
from os.path import dirname

from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
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

  @classmethod
  def do_real_select_literal(cls, type_constraint, candidate, variant_value):
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
      if not type_constraint.satisfied_by(item):
        continue
      if variant_value and not getattr(item, 'name', None) == variant_value:
        continue
      return item
    return None

  def _select_literal(self, candidate, variant_value):
    """Looks for has-a or is-a relationships between the given value and the requested product.

    Returns the resulting product value, or None if no match was made.
    """
    return self.do_real_select_literal(self.selector.type_constraint, candidate, variant_value)

  def _maybe_do_variant_thing(self, step_context):
    variants = self.variants
    if type(self.subject) is Address and self.product is not Variants:
      dep_state = step_context.select_for(self._variant_selector, self.subject, self.variants)
      if type(dep_state) is Waiting:
        return dep_state, None
      elif type(dep_state) is Return:
        # A subject's variants are overridden by any dependent's requested variants, so
        # we merge them left to right here.
        variants = Variants.merge(dep_state.value.default.items(), self.variants)
    return None, variants

  def _handle_selectvariant(self, variants):
    # If there is a variant_key, see whether it has been configured.
    if type(self.selector) is SelectVariant:
      variant_values = [value for key, value in variants
                        if key == self.variant_key] if variants else None
      if not variant_values:
        # Select cannot be satisfied: no variant configured for this key.
        return Noop('Variant key {} was not configured in variants {}', self.variant_key, variants), None
      variant_value = variant_values[0]
    else:
      variant_value = None
    return None, variant_value

  def step(self, step_context):
    # Request default Variants for the subject, so that if there are any we can propagate
    # them to task nodes.
    raise Exception('select node shouldnt be hit anymore self: {}'.format(self))
    state_to_return, variants = self._maybe_do_variant_thing(step_context)
    if state_to_return is not None:
      return state_to_return

    state_to_return, variant_value = self._handle_selectvariant(variants)
    if state_to_return is not None:
      return state_to_return

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

  def collect_dep_values(self, step_context):
    dependencies = []
    dep_values = []
    for selector in self.rule.input_selectors:
      dep_state = step_context.select_for(selector, self.subject, self.variants)

      if type(dep_state) is Waiting:
        if type(selector) is Select:
          # TODO clean this up
          raise Exception(
            """we should never wait on a Select {}
            waiting contents: {}
            self: {}
            deps:
               {}
            node_states
               {}
            selectors to cached vals
               {}""".format(
              selector,
              dep_state.dependencies,
              self,
              '\n       '.join(str(d) for d in dep_state.dependencies),
              step_context._node_states,
              '\n       '.join('{} : {}'.format(k,v) for k, v in step_context._rule_edges._selector_to_state_node_tuple.items())
            ))
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        dep_values.append(dep_state.value)
      elif type(dep_state) is Noop:
        if selector.optional:
          dep_values.append(None)
        else:
          return tuple(), Noop('Was missing (at least) input for {}. {}', selector, dep_state)
      elif type(dep_state) is Throw:
        # NB: propagate thrown exception directly.
        return tuple(), dep_state
      else:
        State.raise_unrecognized(dep_state)
    # If any clause was still waiting on dependencies, indicate it; else execute.
    if dependencies:
      return tuple(), Waiting(dependencies)
    return dep_values, None

  def step(self, step_context):
    # Compute dependencies for the Node, or determine whether it is a Noop.
    dep_values, state = self.collect_dep_values(step_context)
    if state:
      return state
    # Ready to run!
    return Runnable(functools.partial(_run_func_and_check_type,
                                      self.rule.output_product_type,
                                      functools.partial(_satisfied_by, self.rule.constraint),
                                      self.rule.task_func),
                    tuple(dep_values))

  def __repr__(self):
    return '{}(subject={}, variants={}, rule={}' \
      .format(type(self).__name__, self.subject, self.variants, self.rule)

  def __str__(self):
    return repr(self)


class FilesystemNode(datatype('FilesystemNode', ['subject', 'product', 'variants', 'rule']), Node):
  """A native node type for filesystem operations."""

  _FS_PAIRS = {
      (DirectoryListing, Dir),
      (FileContent, File),
      (FileDigest, File),
      (ReadLink, Link),
    }

  is_cacheable = False
  is_inlineable = False

  #rule = None
  extra_repr=None

  @classmethod
  def create(cls, subject, product_type, variants, rule):
    assert (product_type, type(subject)) in cls._FS_PAIRS
    return FilesystemNode(subject, product_type, variants, rule)

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
