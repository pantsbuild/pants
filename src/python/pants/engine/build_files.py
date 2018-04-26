# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
from os.path import dirname, join

import six

from pants.base.project_tree import Dir
from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress, Specs)
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.engine.addressable import AddressableDescriptor, BuildFileAddresses
from pants.engine.fs import FilesContent, PathGlobs, Snapshot
from pants.engine.mapper import AddressFamily, AddressMap, AddressMapper, ResolveError
from pants.engine.objects import Locatable, SerializableFactory, Validatable
from pants.engine.rules import RootRule, SingletonRule, TaskRule, rule
from pants.engine.selectors import Get, Select, SelectDependencies
from pants.engine.struct import Struct
from pants.util.dirutil import fast_relpath_optional
from pants.util.objects import TypeConstraintError, datatype


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


def _key_func(entry):
  key, value = entry
  return key


@rule(AddressFamily, [Select(AddressMapper), Select(Dir)])
def parse_address_family(address_mapper, directory):
  """Given an AddressMapper and a directory, return an AddressFamily.

  The AddressFamily may be empty, but it will not be None.
  """
  patterns = tuple(join(directory.path, p) for p in address_mapper.build_patterns)
  path_globs = PathGlobs.create('',
                                include=patterns,
                                exclude=address_mapper.build_ignore_patterns)
  files_content = yield Get(FilesContent, PathGlobs, path_globs)

  if not files_content:
    raise ResolveError('Directory "{}" does not contain build files.'.format(directory.path))
  address_maps = []
  for filecontent_product in files_content.dependencies:
    address_maps.append(AddressMap.parse(filecontent_product.path,
                                         filecontent_product.content,
                                         address_mapper.parser))
  yield AddressFamily.create(directory.path, address_maps)


class UnhydratedStruct(datatype(['address', 'struct', 'dependencies'])):
  """A product type that holds a Struct which has not yet been hydrated.

  A Struct counts as "hydrated" when all of its members (which are not themselves dependencies
  lists) have been resolved from the graph. This means that hydrating a struct is eager in terms
  of inline addressable fields, but lazy in terms of the complete graph walk represented by
  the `dependencies` field of StructWithDeps.
  """

  def __eq__(self, other):
    if type(self) != type(other):
      return NotImplemented
    return self.struct == other.struct

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.struct)


def _raise_did_you_mean(address_family, name):
  names = [a.target_name for a in address_family.addressables]
  possibilities = '\n  '.join(':{}'.format(target_name) for target_name in sorted(names))
  raise ResolveError('"{}" was not found in namespace "{}". '
                     'Did you mean one of:\n  {}'
                     .format(name, address_family.namespace, possibilities))


@rule(UnhydratedStruct, [Select(AddressMapper), Select(Address)])
def resolve_unhydrated_struct(address_mapper, address):
  """Given an AddressMapper and an Address, resolve an UnhydratedStruct.

  Recursively collects any embedded addressables within the Struct, but will not walk into a
  dependencies field, since those should be requested explicitly by rules.
  """

  address_family = yield Get(AddressFamily, Dir(address.spec_path))

  struct = address_family.addressables.get(address)
  addresses = address_family.addressables
  if not struct or address not in addresses:
    _raise_did_you_mean(address_family, address.target_name)

  dependencies = []
  def maybe_append(outer_key, value):
    if isinstance(value, six.string_types):
      if outer_key != 'dependencies':
        dependencies.append(Address.parse(value,
                                          relative_to=address.spec_path,
                                          subproject_roots=address_mapper.subproject_roots))
    elif isinstance(value, Struct):
      collect_dependencies(value)

  def collect_dependencies(item):
    for key, value in sorted(item._asdict().items(), key=_key_func):
      if not AddressableDescriptor.is_addressable(item, key):
        continue
      if isinstance(value, collections.MutableMapping):
        for _, v in sorted(value.items(), key=_key_func):
          maybe_append(key, v)
      elif isinstance(value, collections.MutableSequence):
        for v in value:
          maybe_append(key, v)
      else:
        maybe_append(key, value)

  collect_dependencies(struct)

  yield UnhydratedStruct(
    filter(lambda build_address: build_address == address, addresses)[0], struct, dependencies)


def hydrate_struct(address_mapper, unhydrated_struct, dependencies):
  """Hydrates a Struct from an UnhydratedStruct and its satisfied embedded addressable deps.

  Note that this relies on the guarantee that DependenciesNode provides dependencies in the
  order they were requested.
  """
  address = unhydrated_struct.address
  struct = unhydrated_struct.struct

  def maybe_consume(outer_key, value):
    if isinstance(value, six.string_types):
      if outer_key == 'dependencies':
        # Don't recurse into the dependencies field of a Struct, since those will be explicitly
        # requested by tasks. But do ensure that their addresses are absolute, since we're
        # about to lose the context in which they were declared.
        value = Address.parse(value,
                              relative_to=address.spec_path,
                              subproject_roots=address_mapper.subproject_roots)
      else:
        value = dependencies[maybe_consume.idx]
        maybe_consume.idx += 1
    elif isinstance(value, Struct):
      value = consume_dependencies(value)
    return value
  # NB: Some pythons throw an UnboundLocalError for `idx` if it is a simple local variable.
  maybe_consume.idx = 0

  # 'zip' the previously-requested dependencies back together as struct fields.
  def consume_dependencies(item, args=None):
    hydrated_args = args or {}
    for key, value in sorted(item._asdict().items(), key=_key_func):
      if not AddressableDescriptor.is_addressable(item, key):
        hydrated_args[key] = value
        continue

      if isinstance(value, collections.MutableMapping):
        container_type = type(value)
        hydrated_args[key] = container_type((k, maybe_consume(key, v))
                                            for k, v in sorted(value.items(), key=_key_func))
      elif isinstance(value, collections.MutableSequence):
        container_type = type(value)
        hydrated_args[key] = container_type(maybe_consume(key, v) for v in value)
      else:
        hydrated_args[key] = maybe_consume(key, value)
    return _hydrate(type(item), address.spec_path, **hydrated_args)

  return consume_dependencies(struct, args={'address': address})


def _hydrate(item_type, spec_path, **kwargs):
  # If the item will be Locatable, inject the spec_path.
  if issubclass(item_type, Locatable):
    kwargs['spec_path'] = spec_path

  try:
    item = item_type(**kwargs)
  except TypeConstraintError as e:
    raise ResolvedTypeMismatchError(e)

  # Let factories replace the hydrated object.
  if isinstance(item, SerializableFactory):
    item = item.create()

  # Finally make sure objects that can self-validate get a chance to do so.
  if isinstance(item, Validatable):
    item.validate()

  return item


@rule(BuildFileAddresses, [Select(AddressMapper), Select(Specs)])
def addresses_from_address_families(address_mapper, specs):
  """Given an AddressMapper and list of Specs, return matching BuildFileAddresses.

  Raises a AddressLookupError if:
     - there were no matching AddressFamilies, or
     - the Spec matches no addresses for SingleAddresses.
  """
  # Capture a Snapshot covering all paths for these Specs, then group by directory.
  snapshot = yield Get(Snapshot, PathGlobs, _spec_to_globs(address_mapper, specs))
  dirnames = set(dirname(f.stat.path) for f in snapshot.files)
  address_families = yield [Get(AddressFamily, Dir(d)) for d in dirnames]

  # NB: `@memoized` does not work on local functions.
  def by_directory():
    if by_directory.cached is None:
      by_directory.cached = {af.namespace: af for af in address_families}
    return by_directory.cached
  by_directory.cached = None

  def raise_empty_address_family(spec):
    raise ResolveError('Path "{}" contains no BUILD files.'.format(spec.directory))

  def exclude_address(address):
    if address_mapper.exclude_patterns:
      address_str = address.spec
      return any(p.search(address_str) is not None for p in address_mapper.exclude_patterns)
    return False

  addresses = []
  included = set()
  def include(address_families, predicate=None):
    matched = False
    for af in address_families:
      for a in af.addressables.keys():
        if not exclude_address(a) and (predicate is None or predicate(a)):
          matched = True
          if a not in included:
            addresses.append(a)
            included.add(a)
    return matched

  for spec in specs.dependencies:
    if type(spec) is DescendantAddresses:
      matched = include(
        af
        for af in address_families
        if fast_relpath_optional(af.namespace, spec.directory) is not None
      )
      if not matched:
        raise AddressLookupError(
          'Spec {} does not match any targets.'.format(spec))
    elif type(spec) is SiblingAddresses:
      address_family = by_directory().get(spec.directory)
      if not address_family:
        raise_empty_address_family(spec)
      include([address_family])
    elif type(spec) is SingleAddress:
      address_family = by_directory().get(spec.directory)
      if not address_family:
        raise_empty_address_family(spec)
      if not include([address_family], predicate=lambda a: a.target_name == spec.name):
        _raise_did_you_mean(address_family, spec.name)
    elif type(spec) is AscendantAddresses:
      include(
        af
        for af in address_families
        if fast_relpath_optional(spec.directory, af.namespace) is not None
      )
    else:
      raise ValueError('Unrecognized Spec type: {}'.format(spec))

  yield BuildFileAddresses(addresses)


def _spec_to_globs(address_mapper, specs):
  """Given a Specs object, return a PathGlobs object for the build files that it matches."""
  patterns = set()
  for spec in specs.dependencies:
    if type(spec) is DescendantAddresses:
      patterns.update(join(spec.directory, '**', pattern)
                      for pattern in address_mapper.build_patterns)
    elif type(spec) in (SiblingAddresses, SingleAddress):
      patterns.update(join(spec.directory, pattern)
                      for pattern in address_mapper.build_patterns)
    elif type(spec) is AscendantAddresses:
      patterns.update(join(f, pattern)
                      for pattern in address_mapper.build_patterns
                      for f in _recursive_dirname(spec.directory))
    else:
      raise ValueError('Unrecognized Spec type: {}'.format(spec))
  return PathGlobs.create('', include=patterns, exclude=address_mapper.build_ignore_patterns)


def _recursive_dirname(f):
  """Given a relative path like 'a/b/c/d', yield all ascending path components like:

        'a/b/c/d'
        'a/b/c'
        'a/b'
        'a'
        ''
  """
  while f:
    yield f
    f = dirname(f)
  yield ''


def create_graph_rules(address_mapper, symbol_table):
  """Creates tasks used to parse Structs from BUILD files.

  :param address_mapper_key: The subject key for an AddressMapper instance.
  :param symbol_table: A SymbolTable instance to provide symbols for Address lookups.
  """
  symbol_table_constraint = symbol_table.constraint()
  return [
    # A singleton to provide the AddressMapper.
    SingletonRule(AddressMapper, address_mapper),
    # Support for resolving Structs from Addresses.
    TaskRule(
      symbol_table_constraint,
      [Select(AddressMapper),
       Select(UnhydratedStruct),
       SelectDependencies(symbol_table_constraint, UnhydratedStruct, field_types=(Address,))],
      hydrate_struct
    ),
    resolve_unhydrated_struct,
    # BUILD file parsing.
    parse_address_family,
    # Spec handling: locate directories that contain build files, and request
    # AddressFamilies for each of them.
    addresses_from_address_families,
    # Root rules representing parameters that might be provided via root subjects.
    RootRule(Address),
    RootRule(BuildFileAddress),
    RootRule(BuildFileAddresses),
    RootRule(Specs),
  ]
