# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections

import six

from pants.build_graph.address import Address
from pants.engine.exp.addressable import (AddressableDescriptor, TypeConstraintError,
                                          strip_config_selector)
from pants.engine.exp.mapper import MappingError
from pants.engine.exp.objects import Resolvable, Serializable, SerializableFactory, Validatable


class ResolveError(Exception):
  """Indicates an error resolving an address to an object."""


class CycleError(ResolveError):
  """Indicates a cycle was detected during object resolution."""


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


class Resolver(Resolvable):
  """Lazily resolves addressables using a graph."""

  def __init__(self, graph, address):
    self._graph = graph
    self._address = address

  def address(self):
    return self._address.spec

  def resolve(self):
    return self._graph.resolve(self._address)

  def __hash__(self):
    return hash((self._graph, self._address))

  def __eq__(self, other):
    return (isinstance(other, Resolver) and
            (self._graph, self._address) == (other._graph, other._address))

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Graph.Resolver(graph={}, address={!r})'.format(self._graph, self._address)


class Graph(object):
  """A lazy, directed acyclic graph of objects. Not necessarily connected."""

  def __init__(self, address_mapper, inline=False):
    """Creates a build graph composed of addresses resolvable by an address mapper.

    :param address_mapper: An address mapper that can resolve the objects addresses point to.
    :type address_mapper: :class:`pants.engine.exp.mapper.AddressMapper`.
    :param bool inline: If `True`, resolved addressables are inlined in the containing object;
                        otherwise a resolvable pointer is used that dynamically traverses to the
                        addressable on every access.
    """
    self._address_mapper = address_mapper

    # TODO(John Sirois): This will need to be eliminated in favor of just using the AddressMapper
    # caching or else also expose an invalidation interface based on address.spec_path - aka
    # AddressMapper.namespace.
    #
    # Our resolution cache.
    self._resolved_by_address = {}

    self._inline = inline

  def resolve(self, address):
    """Resolves the object pointed at by the given `address`.

    The object will be hydrated from the BUILD graph along with any objects it points to.

    The following lifecycle for resolved objects is observed:
    1. The object's containing BUILD file family is parsed if not already parsed.  This is a 'thin'
       parse that just hydrates immediate fields of objects defined in the BUILD file family.
    2. The object's addressed values are all first resolved completely if not already resolved.
    3. The object is reconstructed using the fully resolved values from step 2.
    4. If the reconstructed object is a :class:`pants.engine.exp.objects.SerializableFactory`, its
       `create` method is called to allow for a replacement object to be supplied.
    5. The reconstructed object from step 3 (or replacement object from step 4) is validated if
       it's an instance of :class:`pants.engine.exp.objects.Validatable`.
    6. The fully resolved and validated object is cached and returned.

    :param address: The BUILD graph address to resolve.
    :type address: :class:`pants.build_graph.address.Address`
    :returns: The object pointed at by the given `address`.
    :raises: :class:`ResolveError` if no object was found at the given `address`.
    :raises: :class:`pants.engine.exp.objects.ValidationError` if the object was resolvable but
             invalid.
    """
    try:
      return self._resolve_recursively(address)
    except MappingError as e:
      raise ResolveError('Failed to resolve {}: {}'.format(address, e))

  def _resolve_recursively(self, address, resolve_path=None):
    resolved = self._resolved_by_address.get(address)
    if resolved:
      return resolved

    resolve_path = resolve_path or []
    if address in resolve_path:
      raise CycleError('Cycle detected along path:\n\t{}'
                       .format('\n\t'.join('* {}'.format(a) if a == address else str(a)
                                           for a in resolve_path + [address])))
    resolve_path.append(address)

    obj = self._address_mapper.resolve(strip_config_selector(address))

    def parse_addr(a):
      return Address.parse(a, relative_to=address.spec_path)

    def resolve_item(item, addr=None):
      if Serializable.is_serializable(item):
        hydrated_args = {'address': addr} if addr else {}

        # Recurse on the Serializable's values and hydrates any addressables found.  This unwinds
        # from the leaves thus hydrating item's closure in the inline case.
        for key, value in item._asdict().items():
          is_addressable = AddressableDescriptor.is_addressable(item, key)

          def maybe_addr(x):
            return parse_addr(x) if is_addressable and isinstance(x, six.string_types) else x

          if isinstance(value, collections.MutableMapping):
            container_type = type(value)
            container = container_type()
            container.update((k, resolve_item(maybe_addr(v))) for k, v in value.items())
            hydrated_args[key] = container
          elif isinstance(value, collections.MutableSequence):
            container_type = type(value)
            hydrated_args[key] = container_type(resolve_item(maybe_addr(v)) for v in value)
          else:
            hydrated_args[key] = resolve_item(maybe_addr(value))

        # Re-build the thin Serializable with either fully hydrated objects or Resolvables
        # substituted for all Address values; ie: Only ever expose fully resolved or resolvable
        # closures for requested addresses.
        return self._hydrate(type(item), **hydrated_args)
      elif isinstance(item, Address):
        if self._inline:
          return self._resolve_recursively(item, resolve_path)
        else:
          # TODO(John Sirois): Implement lazy cycle checks across Resolver chains.
          return Resolver(self, address=item)
      else:
        return item

    resolved = resolve_item(obj, addr=address)
    resolve_path.pop(-1)
    self._resolved_by_address[address] = resolved
    return resolved

  @staticmethod
  def _hydrate(item_type, **kwargs):
    try:
      item = item_type(**kwargs)
    except TypeConstraintError as e:
      raise ResolvedTypeMismatchError(e)

    # Let factories replace the hydrated object.
    if isinstance(item, SerializableFactory):
      item = item.create()

    # Finally make sure objects that can self-validate get a chance to do so before we cache
    # them as the pointee of `hydrated_item.address`.
    if isinstance(item, Validatable):
      item.validate()

    return item
