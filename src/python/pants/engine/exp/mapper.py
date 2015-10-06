# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import re

from pants.base.address import Address
from pants.engine.exp import parsers
from pants.engine.exp.objects import Serializable
from pants.util.memo import memoized_property


class MappingError(Exception):
  """Indicates an error mapping addressable objects."""


class UnaddressableObjectError(MappingError):
  """Indicates an un-addressable object was found at the top level."""


class DuplicateNameError(MappingError):
  """Indicates more than one top-level object was found with the same name."""


class AddressMap(object):
  """Maps addressable Serializable objects from a byte source."""

  @classmethod
  def parse(cls, path, parse=None):
    """Parses a source for addressable Serializable objects.

    By default an enhanced JSON parser is used.  The parser admits extra blank lines, comment lines
    and more than one top-level JSON object.  See :`pants.engine.exp.parsers.parse_json` for more
    details on the modified JSON format and the schema for Serializable json objects.

    No matter the parser used, the parsed and mapped addressable objects are all 'thin'; ie: any
    objects they point to in other namespaces or even in the same namespace but from a seperate
    source are left as unresolved pointers.

    :param string path: The path to the byte source containing serialized objects.
    :param parse: The parse function to use; by default a json parser.
    :type parse: :class:`collection.Callable` that accepts a byte source and returns a list of all
                 addressable Serializable objects parsed from it.
    """
    parse = parse or parsers.parse_json
    objects = parse(path)
    objects_by_name = {}
    for obj in objects:
      if not Serializable.is_serializable(obj):
        raise UnaddressableObjectError('Parsed a non-serilizable object: {!r}'.format(obj))
      attributes = obj._asdict()

      name = attributes.get('name')
      if not name:
        raise UnaddressableObjectError('Parsed a non-addressable object: {!r}'.format(obj))

      if name in objects_by_name:
        raise DuplicateNameError('An object already exists at {!r} with name {!r}: {!r}.  Cannot '
                                 'map {!r}'.format(path, name, objects_by_name[name], obj))

      objects_by_name[name] = obj
    return cls(path, objects_by_name)

  def __init__(self, path, objects_by_name):
    """Not intended for direct use, instead see `parse`."""
    self._path = path
    self._objects_by_name = objects_by_name

  @property
  def path(self):
    """Return the path to the byte source this address map's objects were pased from.

    :rtype: string
    """
    return self._path

  @property
  def objects_by_name(self):
    """Return a mapping from object name to the parsed 'thin' addressable object.

    :rtype: dict from string to thin addressable objects.
    """
    return self._objects_by_name

  def __repr__(self):
    return 'AddressMap(path={!r}, objects_by_name={!r})'.format(self._path, self._objects_by_name)


class DifferingFamiliesError(MappingError):
  """Indicates an attempt was made to merge address maps from different families together."""


class AddressFamily(object):
  """Represents the family of addressed objects in a namespace.

  An address family can be composed of the addressed objects from one or more underlying address
  sources.
  """

  @classmethod
  def create(cls, build_root, address_maps):
    """Creates an address family from the given set of address maps.

    :param string build_root: The absolute path of the root of the namespace. All address maps must
                              be hydrated from child paths of the build root.
    :param address_maps: The family of maps that form this namespace.
    :type address_maps: :class:`collections.Iterable` of :class:`AddressMap`
    :returns: a new address family.
    :rtype: :class:`AddressFamily`
    :raises: :class:`MappingError` if the given address maps do not form a family.
    """
    if not address_maps:
      raise TypeError('Handed an empty set of AddressMaps - must be given at least one.')

    spec_paths = {os.path.dirname(address_map.path) for address_map in address_maps}
    if len(spec_paths) > 1:
      raise DifferingFamiliesError('Expected all AddressMaps to share the same parent directory '
                                   'but given a mix of parent directories:\n\t{}'
                                   .format('\n\t'.join(sorted(spec_paths))))
    spec_path = os.path.relpath(spec_paths.pop(), build_root)
    if spec_path == '.':
      spec_path = ''

    objects_by_name = {}
    for address_map in address_maps:
      current_path = address_map.path
      for name, obj in address_map.objects_by_name.items():
        previous = objects_by_name.get(name)
        if previous:
          previous_path, _ = previous
          raise DuplicateNameError('An object with name {name!r} is already defined in '
                                   '{previous_path!r}, will not overwrite with {obj!r} from '
                                   '{current_path!r}.'
                                   .format(name=name,
                                           previous_path=previous_path,
                                           obj=obj,
                                           current_path=current_path))
        objects_by_name[name] = (current_path, obj)
    return AddressFamily(namespace=spec_path,
                         objects_by_name={name: obj for name, (_, obj) in objects_by_name.items()})

  def __init__(self, namespace, objects_by_name):
    """Not intended for direct use, instead see `create`."""
    self._namespace = namespace
    self._objects_by_name = objects_by_name

  @property
  def namespace(self):
    """Return the namespace path of this address family.

    :rtype: string
    """
    return self._namespace

  # TODO(John Sirois): Support in-memory injection of fully-hydrated (synthetic) addressables in
  # this family's namespace (spec_path).  It would be appealing to support this by
  # expanding/re-defining the family and growing it to include an in-memory AddressMap sibling that
  # would carry the injection(s).
  @memoized_property
  def addressables(self):
    """Return a mapping from address to thin addressable objects in this namespace.

    :rtype: dict from :class:`pants.base.address.Address` to thin addressable objects.
    """
    return {Address(spec_path=self._namespace, target_name=name): obj
            for name, obj in self._objects_by_name.items()}

  def __repr__(self):
    return 'AddressFamily(namespace={!r}, objects_by_name={!r})'.format(self._namespace,
                                                                        self._objects_by_name)


def walk_addressables(parser, build_root, rel_path=None, build_pattern=None, spec_excludes=None):
  build_pattern = re.compile(build_pattern or r'^BUILD(\.[a-zA-Z0-9_-]+)?$')
  map_root = os.path.join(build_root, rel_path or '')
  for root, dirs, files in os.walk(map_root):
    if spec_excludes:
      for i, d in enumerate(dirs):
        dir_path = os.path.join(root, d)
        if dir_path in spec_excludes:
          del dirs[i]
    maps = []
    for f in files:
      if build_pattern.match(f):
        build_path = os.path.join(root, f)
        maps.append(AddressMap.parse(build_path, parser))
    if maps:
      for address, obj in AddressFamily.create(build_root, maps).addressables.items():
        yield address, obj
