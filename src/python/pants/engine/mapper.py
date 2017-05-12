# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import OrderedDict

from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from pants.build_graph.address import BuildFileAddress
from pants.engine.objects import Serializable
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
  def parse(cls, filepath, filecontent, symbol_table_cls, parser_cls):
    """Parses a source for addressable Serializable objects.

    No matter the parser used, the parsed and mapped addressable objects are all 'thin'; ie: any
    objects they point to in other namespaces or even in the same namespace but from a seperate
    source are left as unresolved pointers.

    :param string filepath: The path to the byte source containing serialized objects.
    :param string filecontent: The content of byte source containing serialized objects to be parsed.
    :param symbol_table_cls: The symbol table cls to expose a symbol table dict.
    :type symbol_table_cls: A :class:`pants.engine.parser.SymbolTable`.
    :param parser_cls: The parser cls to use.
    :type parser_cls: A :class:`pants.engine.parser.Parser`.
    """
    try:
      objects = parser_cls.parse(filepath, filecontent, symbol_table_cls)
    except Exception as e:
      raise MappingError('Failed to parse {}:\n{}'.format(filepath, e))
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
                                 'map {!r}'.format(filepath, name, objects_by_name[name], obj))
      objects_by_name[name] = obj
    return cls(filepath, OrderedDict(sorted(objects_by_name.items())))


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
  def create(cls, spec_path, address_maps):
    """Creates an address family from the given set of address maps.

    :param spec_path: The directory prefix shared by all address_maps.
    :param address_maps: The family of maps that form this namespace.
    :type address_maps: :class:`collections.Iterable` of :class:`AddressMap`
    :returns: a new address family.
    :rtype: :class:`AddressFamily`
    :raises: :class:`MappingError` if the given address maps do not form a family.
    """
    if spec_path == b'.':
      spec_path = ''
    for address_map in address_maps:
      if not address_map.path.startswith(spec_path):
        raise DifferingFamiliesError('Expected AddressMaps to share the same parent directory {}, '
                                     'but received: {}'
                                     .format(spec_path, address_map.path))


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
                         objects_by_name=OrderedDict((name, (path, obj)) for name, (path, obj)
                                                      in sorted(objects_by_name.items())))

  @memoized_property
  def addressables(self):
    """Return a mapping from BuildFileAddress to thin addressable objects in this namespace.

    :rtype: dict from :class:`pants.build_graph.address.BuildFileAddress` to thin addressable
            objects.
    """
    return {
      BuildFileAddress(rel_path=path, target_name=name): obj
      for name, (path, obj) in self.objects_by_name.items()
    }

  def __eq__(self, other):
    if not type(other) == type(self):
      return NotImplemented
    return self.namespace == other.namespace

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.namespace)

  def __repr__(self):
    return 'AddressFamily(namespace={!r}, objects_by_name={!r})'.format(
        self.namespace, self.objects_by_name.keys())


class ResolveError(MappingError):
  """Indicates an error resolving targets."""


class AddressMapper(object):
  """Configuration to parse build files matching a filename pattern."""

  def __init__(self,
               symbol_table_cls,
               parser_cls,
               build_patterns=None,
               build_ignore_patterns=None,
               exclude_target_regexps=None,
               subproject_roots=None):
    """Create an AddressMapper.

    Both the set of files that define a mappable BUILD files and the parser used to parse those
    files can be customized.  See the `pants.engine.parsers` module for example parsers.

    :param symbol_table_cls: The symbol table cls to expose a symbol table dict.
    :type symbol_table_cls: A :class:`pants.engine.parser.SymbolTable`.
    :param parser_cls: The BUILD file parser cls to use.
    :type parser_cls: A :class:`pants.engine.parser.Parser`.
    :param tuple build_patterns: A tuple of fnmatch-compatible patterns for identifying BUILD files
                                 used to resolve addresses.
    :param list build_ignore_patterns: A list of path ignore patterns used when searching for BUILD files.
    :param list exclude_target_regexps: A list of regular expressions for excluding targets.
    """
    self.symbol_table_cls = symbol_table_cls
    self.parser_cls = parser_cls
    self.build_patterns = build_patterns or (b'BUILD', b'BUILD.*')
    self.build_ignore_patterns = PathSpec.from_lines(GitWildMatchPattern, build_ignore_patterns or [])
    self._exclude_target_regexps = exclude_target_regexps or []
    self.exclude_patterns = [re.compile(pattern) for pattern in self._exclude_target_regexps]
    self.subproject_roots = subproject_roots or []

  def __eq__(self, other):
    if self is other:
      return True
    if type(other) != type(self):
      return NotImplemented
    return (other.symbol_table_cls == self.symbol_table_cls and
            other.build_patterns == self.build_patterns and
            other.parser_cls == self.parser_cls)

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    # Compiled regexes are not hashable.
    return hash((self.symbol_table_cls, self.parser_cls))

  def __repr__(self):
    return 'AddressMapper(parser={}, symbol_table={}, build_patterns={})'.format(
      self.parser_cls, self.symbol_table_cls, self.build_patterns)

  def __str__(self):
    return repr(self)
