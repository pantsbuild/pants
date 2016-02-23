# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.build_graph.address import Address
from pants.engine.exp.objects import Serializable
from pants.util.memo import memoized_property
from pants.util.objects import datatype


class MappingError(Exception):
  """Indicates an error mapping addressable objects."""


class UnaddressableObjectError(MappingError):
  """Indicates an un-addressable object was found at the top level."""


class DuplicateNameError(MappingError):
  """Indicates more than one top-level object was found with the same name."""


class AddressMap(datatype('AddressMap', ['path', 'objects_by_name'])):
  """Maps addressable Serializable objects from a byte source.

  To construct an AddressMap, use `parse`.

  :param path: The path to the byte source this address map's objects were pased from.
  :param objects_by_name: A dict mapping from object name to the parsed 'thin' addressable object.
  """

  @classmethod
  def parse(cls, path, symbol_table_cls, parser_cls):
    """Parses a source for addressable Serializable objects.

    No matter the parser used, the parsed and mapped addressable objects are all 'thin'; ie: any
    objects they point to in other namespaces or even in the same namespace but from a seperate
    source are left as unresolved pointers.

    :param string path: The path to the byte source containing serialized objects.
    :param parser_cls: The parser cls to use.
    :type parser_cls: A :class:`pants.engine.exp.parser.Parser`
    """
    objects = parser_cls.parse(path, symbol_table_cls)
    objects_by_name = {}
    for obj in objects:
      if not Serializable.is_serializable(obj):
        raise UnaddressableObjectError('Parsed a non-serializable object: {!r}'.format(obj))
      attributes = obj._asdict()

      name = attributes.get('name')
      if not name:
        raise UnaddressableObjectError('Parsed a non-addressable object: {!r}'.format(obj))

      if name in objects_by_name:
        raise DuplicateNameError('An object already exists at {!r} with name {!r}: {!r}.  Cannot '
                                 'map {!r}'.format(path, name, objects_by_name[name], obj))

      objects_by_name[name] = obj
    return cls(path, objects_by_name)


class DifferingFamiliesError(MappingError):
  """Indicates an attempt was made to merge address maps from different families together."""


class AddressFamily(datatype('AddressFamily', ['namespace', 'objects_by_name'])):
  """Represents the family of addressed objects in a namespace.

  To create an AddressFamily, use `create`.

  An address family can be composed of the addressed objects from zero or more underlying address
  sources. An "empty" AddressFamily is legal, and is the result when there are not build files in a
  particular namespace.

  :param namespace: The namespace path of this address family.
  :param objects_by_name: A dict mapping from object name to the parsed 'thin' addressable object.
  """

  @classmethod
  def create(cls, build_root, spec_path, address_maps):
    """Creates an address family from the given set of address maps.

    :param string build_root: The absolute path of the root of the namespace. All address maps must
                              be hydrated from child paths of the build root.
    :param address_maps: The family of maps that form this namespace.
    :type address_maps: :class:`collections.Iterable` of :class:`AddressMap`
    :returns: a new address family.
    :rtype: :class:`AddressFamily`
    :raises: :class:`MappingError` if the given address maps do not form a family.
    """
    abs_spec_path = os.path.join(build_root, spec_path)
    for address_map in address_maps:
      if not address_map.path.startswith(abs_spec_path):
        raise DifferingFamiliesError('Expected AddressMaps to share the same parent directory {}, '
                                     'but received: {}'
                                     .format(spec_path, address_map.path))

    if spec_path == b'.':
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

  @memoized_property
  def addressables(self):
    """Return a mapping from address to thin addressable objects in this namespace.

    :rtype: dict from :class:`pants.build_graph.address.Address` to thin addressable objects.
    """
    return {Address(spec_path=self.namespace, target_name=name): obj
            for name, obj in self.objects_by_name.items()}

  def __eq__(self, other):
    if not type(other) == type(self):
      return NotImplemented
    return self.namespace == other.namespace

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.namespace)

  def __repr__(self):
    return 'AddressFamily(namespace={!r}, objects_by_name={!r})'.format(self.namespace,
                                                                        self.objects_by_name.keys())


class ResolveError(MappingError):
  """Indicates an error resolving targets."""


class AddressMapper(object):
  """Maps addresses to the objects they point to."""

  def __init__(self, build_root, symbol_table_cls, parser_cls, build_pattern=None):
    """Creates an address mapper rooted at the given `build_root`.

    Both the set of files that define a mappable BUILD files and the parser used to parse those
    files can be customized.  See the `pants.engine.exp.parsers` module for example parsers.

    :param string build_root: The root of the BUILD files; typically the code repository root
                              directory.
    :param string build_pattern: A regular expression for identifying BUILD files used to resolve
                                 addresses; by default looks for `BUILD*` files.
    :param parser_cls: The BUILD file parser cls to use.
    :type parser_cls: A :class:`pants.engine.exp.parser.Parser`
    """
    self._build_root = os.path.realpath(build_root)
    self._symbol_table_cls = symbol_table_cls
    self._parser_cls = parser_cls
    self._build_pattern = re.compile(build_pattern or r'^BUILD(\.[a-zA-Z0-9_-]+)?$')

  def _find_build_files(self, dir_path):
    abs_dir_path = os.path.join(self._build_root, dir_path)
    if not os.path.isdir(abs_dir_path):
      raise ResolveError('Expected {} to be a directory containing build files.'.format(dir_path))
    for f in os.listdir(abs_dir_path):
      if self._build_pattern.match(f):
        abs_build_file = os.path.join(abs_dir_path, f)
        if os.path.isfile(abs_build_file):
          yield abs_build_file

  def _parse(self, path):
    return AddressMap.parse(path, self._symbol_table_cls, parser_cls=self._parser_cls)

  def family(self, namespace):
    """Load the AddressFamily in the given namespace (which may be empty).

    :param string namespace: The namespace of the address family to load.
    :returns: The address family at the given namespace.
    :rtype: :class:`AddressFamily`
    """
    build_files = list(self._find_build_files(namespace))
    return AddressFamily.create(self._build_root, namespace, [self._parse(bf) for bf in build_files])

  def __eq__(self, other):
    if self is other:
      return True
    if type(other) != type(self):
      return NotImplemented
    return (other._build_root == self._build_root and
            other._symbol_table_cls == self._symbol_table_cls and
            other._build_pattern == self._build_pattern and
            other._parser_cls == self._parser_cls)

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self._build_root)
