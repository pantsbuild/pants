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
from pants.engine.exp.serializable import Serializable
from pants.util.memo import memoized_method


class ResolveError(Exception):
  """Indicates an error resolving an address to an object."""


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

  @memoized_method
  def resolve(self, address):
    """Resolves the object pointed at by the given `address`.

    The object will be hydrated from the BUILD graph along with any objects it points to.

    :param address: The BUILD graph address to resolve.
    :type address: :class:`pants.base.address.Address`
    :returns: The object pointed at by the given `address`.
    :raises: :class:`ResolveError` if no object was found at the given `address`.
    """
    address_family = self._address_family(address.spec_path)
    obj = address_family.addressables.get(address)
    if not obj:
      raise ResolveError('Object with address {} was not found'.format(address))

    def resolve_item(item):
      if Serializable.is_serializable(item):
        hydrated_args = {}
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

        item_type = type(item)
        hydrated_item = item_type(**hydrated_args)
        return hydrated_item
      elif isinstance(item, Addressed):
        return self._resolve_item(context_address=address, addressed=item)
      else:
        return item

    return resolve_item(obj)

  def _find_sources(self, path):
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
    for source in self._find_sources(spec_path):
      address_maps.append(AddressMap.parse(source, parse=self._parser))
    return AddressFamily.create(self._build_root, address_maps)

  def _resolve_item(self, context_address, addressed):
    address = Address.parse(addressed.address, relative_to=context_address.spec_path)
    obj = self.resolve(address)
    if not isinstance(obj, addressed.addressed_type):
      raise ResolveError('Found a {} when resolving {} for {}, expected a {}'
                         .format(type(obj).__name__,
                                 address,
                                 context_address,
                                 addressed.addressed_type.__name__))
    return obj
