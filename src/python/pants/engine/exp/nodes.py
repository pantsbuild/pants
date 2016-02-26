# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import cPickle as pickle
from abc import abstractmethod, abstractproperty
from binascii import hexlify
from collections import defaultdict
from hashlib import sha1
from struct import Struct as StdlibStruct

import six

from pants.build_graph.address import Address
from pants.engine.exp.addressable import parse_variants
from pants.engine.exp.objects import SerializationError
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


class SubjectKey(object):
  """Holds the digest for a Subject, which uniquely identifies it.

  The `_hash` is a memoized 32 bit integer hashcode computed from the digest.

  The `string` field holds the string representation of the subject, but is optional (usually only
  used when debugging is enabled).

  NB: Because `string` is not included in equality comparisons, we cannot just use `datatype` here.
  """

  __slots__ = ['_digest', '_hash', '_string']

  # The digest implementation used for SubjectKeys.
  _DIGEST_IMPL = sha1
  _DIGEST_SIZE = _DIGEST_IMPL().digest_size

  # A struct.Struct definition for grabbing the first 4 bytes off of a digest of
  # size DIGEST_SIZE, and discarding the rest.
  _32_BIT_STRUCT = StdlibStruct('<l' + ('x' * (_DIGEST_SIZE - 4)))

  @classmethod
  def create(cls, blob, string=None):
    """Given a blob, hash it to construct a SubjectKey.

    :param blob: Binary content to hash.
    :param string: An optional human-readable representation of the blob for debugging purposes.
    """
    digest = cls._DIGEST_IMPL(blob).digest()
    _hash = cls._32_BIT_STRUCT.unpack(digest)[0]
    return cls(digest, _hash, string)

  def __init__(self, digest, _hash, string):
    """Not for direct use: construct a SubjectKey via `create` instead."""
    self._digest = digest
    self._hash = _hash
    self._string = string

  @property
  def string(self):
    return self._string

  def set_string(self, string):
    """Sets the string for a SubjectKey after construction.

    Since the string representation is not involved in `eq` or `hash`, this allows the key to be
    used for lookups before its string representation has been stored, and then only generated
    it the object will remain in use.
    """
    self._string = string

  def __hash__(self):
    return self._hash

  def __eq__(self, other):
    return type(other) == SubjectKey and self._digest == other._digest

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Key({}{})'.format(
        hexlify(self._digest),
        '' if self._string is None else ':[{}]'.format(self._string))

  def __str__(self):
    return repr(self)


class Subjects(object):
  """Stores and creates unique keys for input Serializable objects.

  TODO: A placeholder for the cache/content-addressability implementation from
    https://github.com/pantsbuild/pants/issues/2870
  """

  def __init__(self, debug=True, protocol=None):
    self._storage = dict()
    self._debug = debug
    # TODO: Have seen strange inconsistencies with pickle protocol version 1/2 (ie, the
    # binary versions): in particular, bytes added into the middle of otherwise identical
    # objects.
    self._protocol = protocol if protocol is not None else 0

  def __len__(self):
    return len(self._storage)

  def put(self, obj):
    """Serialize and hash a Serializable, returning a unique key to retrieve it later."""
    return self.maybe_put(obj)[0]

  def maybe_put(self, obj):
    """Similar to put, but returns a tuple of key, value.

    If the object had already been stored, returns None for the value. Always returns the key.
    """
    try:
      blob = pickle.dumps(obj, protocol=self._protocol)
    except Exception as e:
      # Unfortunately, pickle can raise things other than PickleError instances.  For example it
      # will raise ValueError when handed a lambda; so we handle the otherwise overly-broad
      # `Exception` type here.
      raise SerializationError('Failed to pickle {}: {}'.format(obj, e))

    # Hash the blob and store it if it does not exist.
    key = SubjectKey.create(blob)
    stored_key, stored_value = self._storage.setdefault(key, (key, blob))
    if stored_key is key:
      # The key was just created for the first time. Add its `str` representation if we're in debug.
      if self._debug:
        key.set_string(str(obj))
      return stored_key, stored_value
    else:
      # Entry already existed.
      return stored_key, None

  def put_entry(self, key, value):
    """Store an entry returned by `maybe_put` (presumably in some other Subjects intance)."""
    if type(key) is not SubjectKey:
      raise ValueError('Expected a SubjectKey key. Got: {}'.format(key))
    if type(value) is not six.binary_type:
      raise ValueError('Expected a binary value. Got type: {}'.format(type(value)))
    return self._storage.setdefault(key, (key, value))[0]

  def get(self, key):
    """Given a key, return its deserialized content.

    Note that since this is not a cache, if we do not have the content for the object, this
    operation fails noisily.
    """
    return pickle.loads(self._storage[key][1])


class Node(object):
  @classmethod
  def validate_node(cls, node):
    if not isinstance(node, Node):
      raise ValueError('Value {} is not a Node.'.format(node))
    if type(node.subject_key) is not SubjectKey:
      raise ValueError('Node {} has a non-SubjectKey subject.'.format(node))

  @abstractproperty
  def subject_key(self):
    """The subject for this Node."""

  @abstractproperty
  def product(self):
    """The output product for this Node."""

  @abstractproperty
  def variants(self):
    """The variants for this Node."""

  @abstractmethod
  def step(self, subject, dependency_states, step_context):
    """Given a dict of the dependency States for this Node, returns the current State of the Node.

    The NodeBuilder parameter provides a way to construct Nodes that require information about
    installed tasks.

    TODO: The NodeBuilder is now a StepContext... rename everywhere.

    After this method returns a non-Waiting state, it will never be visited again for this Node.

    TODO: Not all Node types actually need the `subject` as a parameter... can that be pushed out
    as an explicit dependency type? Perhaps the "is-a/has-a" checks should be native outside of Node?
    """


class SelectNode(datatype('SelectNode', ['subject_key', 'product', 'variants', 'variant_key']), Node):
  """A Node that selects a product for a subject.

  A Select can be satisfied by multiple sources, but fails if multiple sources produce a value. The
  'variants' field represents variant configuration that is propagated to dependencies. When
  a task needs to consume a product as configured by the variants map, it uses the SelectVariant
  selector, which introduces the 'variant' value to restrict the names of values selected by a
  SelectNode.
  """

  def _variants_node(self):
    # TODO: This super-broad check is crazy expensive. Should reduce to just doing Variants
    # lookups for literal/addressable products.
    if self.product != Variants:
      return SelectNode(self.subject_key, Variants, self.variants, None)
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

  def step(self, subject, dependency_states, step_context):
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
    literal_value = self._select_literal(subject, variant_value)
    if literal_value is not None:
      return Return(literal_value)

    # Else, attempt to use a configured task to compute the value.
    has_waiting_dep = False
    dependencies = list(step_context.task_nodes(self.subject_key, self.product, variants))
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
      return Throw(ConflictingProducersError(subject, self.product, matches))
    elif len(matches) == 1:
      return Return(matches.values()[0])
    return Noop('No source of {}.'.format(self))


class DependenciesNode(datatype('DependenciesNode', ['subject_key', 'product', 'variants', 'dep_product', 'field']), Node):
  """A Node that selects the given Product for each of the items in a field `field` on this subject.

  Begins by selecting the `dep_product` for the subject, and then selects a product for each
  member a collection named `field` on the dep_product.

  The value produced by this Node guarantees that the order of the provided values matches the
  order of declaration in the list `field` of the `dep_product`.
  """

  def _dep_product_node(self):
    return SelectNode(self.subject_key, self.dep_product, self.variants, None)

  def _dependency_nodes(self, step_context, dep_product):
    for dependency in getattr(dep_product, self.field or 'dependencies'):
      variants = self.variants
      if isinstance(dependency, Address):
        # If a subject has literal variants for particular dependencies, they win over all else.
        dependency, literal_variants = parse_variants(dependency)
        variants = Variants.merge(variants, literal_variants)
      yield SelectNode(step_context.introduce_subject(dependency), self.product, variants, None)

  def step(self, subject, dependency_states, step_context):
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
    dependencies = list(self._dependency_nodes(step_context, dep_product_state.value))
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


class ProjectionNode(datatype('ProjectionNode', ['subject_key', 'product', 'variants', 'projected_subject', 'fields', 'input_product']), Node):
  """A Node that selects the given input Product for the Subject, and then selects for a new subject.

  TODO: This is semantically very similar to DependenciesNode (which might be considered to be a
  multi-field projection for the contents of a list). Should be looking for ways to merge them.
  """

  def _input_node(self):
    return SelectNode(self.subject_key, self.input_product, self.variants, None)

  def _output_node(self, step_context, projected_subject):
    return SelectNode(step_context.introduce_subject(projected_subject), self.product, self.variants, None)

  def step(self, subject, dependency_states, step_context):
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
    output_node = self._output_node(step_context, projected_subject)

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


class TaskNode(datatype('TaskNode', ['subject_key', 'product', 'variants', 'func', 'clause']), Node):

  def step(self, subject, dependency_states, step_context):
    # Compute dependencies.
    dep_values = []
    dependencies = []
    for select in self.clause:
      dep = select.construct_node(self.subject_key, self.variants)
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


class StepContext(object):
  """Encapsulates external state and the details of creating Nodes.

  This avoids giving Nodes direct access to the task list or subject set.
  """

  def __init__(self, node_builder, subjects):
    self._node_builder = node_builder
    self._subjects = subjects
    self._introduced_subjects = dict()

  def introduce_subject(self, subject):
    """Introduces a potentially new Subject, and returns a SubjectKey."""
    key, value = self._subjects.maybe_put(subject)
    if value is not None:
      # This subject had not been seen before by this Subjects instance.
      self._introduced_subjects[key] = value
    return key

  def task_nodes(self, subject_key, product, variants):
    """Yields task Node instances which might be able to provide a value for the given inputs."""
    return self._node_builder.task_nodes(subject_key, product, variants)

  @property
  def introduced_subjects(self):
    """Return a dict of any subjects that were introduced by the running Step."""
    return self._introduced_subjects
