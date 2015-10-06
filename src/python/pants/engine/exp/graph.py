# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import os
import re

import six

from pants.base.address import Address
from pants.engine.exp.addressable import Addressed
from pants.engine.exp.mapper import AddressFamily, AddressMap
from pants.engine.exp.objects import Serializable, SerializableFactory, Validatable
from pants.util.memo import memoized_method


class ResolveError(Exception):
  """Indicates an error resolving an address to an object."""


class CycleError(ResolveError):
  """Indicates a cycle was detected during object resolution."""


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


# TODO(John Sirois): Support in-memory injection of fully-hydrated (synthetic) addressables.
class Graph(object):
  """A lazy, directed acyclic graph of objects. Not necessarily connected."""

  def __init__(self, build_root, build_pattern=None, parser=None):
    """Creates a build graph rooted at the given `build_root`.

    Both the set of files that define a BUILD graph and the parser used to parse those files can be
    customized.  See the `pants.engine.exp.parsers` module for example parsers.

    :param string build_pattern: A regular expression for identifying BUILD files used to resolve
                                 addresses; by default looks for `BUILD*` files.
    :param parser: The BUILD file parser to use; by default a JSON BUILD file format parser.
    :type parser: A :class:`collections.Callable` that takes a byte string and produces a list of
                  parsed addressable Serializable objects found in the byte string.
    """
    self._build_root = os.path.realpath(build_root)
    self._build_pattern = re.compile(build_pattern or r'^BUILD(\.[a-zA-Z0-9_-]+)?$')
    self._parser = parser

    # Our resolution cache.
    self._resolved_by_address = {}

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
    :type address: :class:`pants.base.address.Address`
    :returns: The object pointed at by the given `address`.
    :raises: :class:`ResolveError` if no object was found at the given `address`.
    :raises: :class:`pants.engine.exp.objects.ValidationError` if the object was resolvable but
             invalid.
    """
    return self._resolve_recursively(address)

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

    address_family = self._address_family(address.spec_path)
    obj = address_family.addressables.get(address)
    if not obj:
      raise ResolveError('Object with address {} was not found'.format(address))

    def resolve_item(item, addr=None):
      if Serializable.is_serializable(item):
        hydrated_args = {'address': addr} if addr else {}

        # Recurse on the Serializable's values and hydrate any `Addressed` found.  This unwinds from
        # the leaves thus hydrating item's closure.
        for key, value in item._asdict().items():
          if isinstance(value, collections.MutableMapping):
            container_type = type(value)
            container = container_type()
            container.update((k, resolve_item(v)) for k, v in value.items())
            hydrated_args[key] = container
          elif isinstance(value, collections.Iterable) and not isinstance(value, six.string_types):
            container_type = type(value)
            hydrated_args[key] = container_type(resolve_item(v) for v in value)
          else:
            hydrated_args[key] = resolve_item(value)

        # Re-build the thin Serializable with fully hydrated objects substituted for all Addressed
        # values; ie: Only ever expose full resolved closures for requested addresses.
        item_type = type(item)
        hydrated_item = item_type(**hydrated_args)

        # Let factories replace the hydrated object.
        if isinstance(hydrated_item, SerializableFactory):
          hydrated_item = hydrated_item.create()

        # Finally make sure objects that can self-validate get a chance to do so before we cache
        # them as the pointee of `hydrated_item.address`.
        if isinstance(hydrated_item, Validatable):
          hydrated_item.validate()

        return hydrated_item
      elif isinstance(item, Addressed):
        referenced_address = Address.parse(spec=item.address_spec, relative_to=address.spec_path)
        referenced_item = self._resolve_recursively(referenced_address, resolve_path)
        if not item.type_constraint.satisfied_by(referenced_item):
          raise ResolvedTypeMismatchError('Found a {} when resolving {} for {}, expected a {!r}'
                                          .format(type(referenced_item).__name__,
                                                  referenced_address,
                                                  address,
                                                  item.type_constraint))
        return referenced_item
      else:
        return item

    resolved = resolve_item(obj, addr=address)
    resolve_path.pop(-1)
    self._resolved_by_address[address] = resolved
    return resolved

  def _find_build_file_sources(self, path):
    abspath = os.path.realpath(os.path.join(self._build_root, path))
    if not os.path.isdir(abspath):
      raise ResolveError('Expected {} to be a directory containing build files.'.format(path))
    for f in os.listdir(abspath):
      if self._build_pattern.match(f):
        absfile = os.path.join(abspath, f)
        if os.path.isfile(absfile):
          yield absfile

  @memoized_method
  def _address_family(self, spec_path):
    address_maps = []
    for source in self._find_build_file_sources(spec_path):
      address_maps.append(AddressMap.parse(source, parse=self._parser))
    return AddressFamily.create(self._build_root, address_maps)
