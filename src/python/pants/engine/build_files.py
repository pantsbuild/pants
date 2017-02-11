# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
from fnmatch import fnmatch
from os.path import basename, dirname, join

import six

from pants.base.project_tree import Dir, File
from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import AddressableDescriptor, Addresses, Exactly, TypeConstraintError
from pants.engine.fs import DirectoryListing, Files, FilesContent, Path, PathGlobs, Snapshot
from pants.engine.mapper import AddressFamily, AddressMap, AddressMapper, ResolveError
from pants.engine.objects import Locatable, SerializableFactory, Validatable
from pants.engine.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants.engine.struct import Struct
from pants.util.objects import datatype


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


def _key_func(entry):
  key, value = entry
  return key


class BuildDirs(datatype('BuildDirs', ['dependencies'])):
  """A list of Stat objects for directories containing build files."""


class BuildFiles(datatype('BuildFiles', ['path_globs'])):
  """A wrapper around PathGlobs that are known to match a build file pattern."""


def filter_buildfile_paths(address_mapper, directory_listing):
  def match(stat):
    # Short circuit for ignored paths.
    if address_mapper.build_ignore_patterns.match_file(stat.path):
      return False

    return (type(stat) is File and any(fnmatch(basename(stat.path), pattern)
                                       for pattern in address_mapper.build_patterns))

  # TODO: Skip straight to requesting a Snapshot per directory, rather than re-requesting one here.
  matches = tuple(stat.path for stat in directory_listing.dependencies if match(stat))
  return BuildFiles(PathGlobs.create('', include=matches, exclude=()))


def parse_address_family(address_mapper, path, build_files_content):
  """Given the contents of the build files in one directory, return an AddressFamily.

  The AddressFamily may be empty, but it will not be None.
  """
  if not build_files_content.dependencies:
    raise ResolveError('Directory "{}" does not contain build files.'.format(path))
  address_maps = []
  for filecontent_product in build_files_content.dependencies:
    address_maps.append(AddressMap.parse(filecontent_product.path,
                                         filecontent_product.content,
                                         address_mapper.symbol_table_cls,
                                         address_mapper.parser_cls,
                                         address_mapper.exclude_patterns))
  return AddressFamily.create(path.path, address_maps)


class UnhydratedStruct(datatype('UnhydratedStruct', ['address', 'struct', 'dependencies'])):
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
  possibilities = '\n  '.join(str(a) for a in address_family.addressables)
  raise ResolveError('A Struct was not found in namespace {} for name "{}". '
                     'Did you mean one of?:\n  {}'.format(address_family.namespace, name, possibilities))


def resolve_unhydrated_struct(address_family, address):
  """Given an Address and its AddressFamily, resolve an UnhydratedStruct.

  Recursively collects any embedded addressables within the Struct, but will not walk into a
  dependencies field, since those are requested explicitly by tasks using SelectDependencies.
  """

  struct = address_family.addressables.get(address)
  addresses = address_family.addressables
  if not struct or address not in addresses:
    _raise_did_you_mean(address_family, address.target_name)

  dependencies = []
  def maybe_append(outer_key, value):
    if isinstance(value, six.string_types):
      if outer_key != 'dependencies':
        dependencies.append(Address.parse(value, relative_to=address.spec_path))
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

  return UnhydratedStruct(
    filter(lambda build_address: build_address == address, addresses)[0], struct, dependencies)


def hydrate_struct(unhydrated_struct, dependencies):
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
        value = Address.parse(value, relative_to=address.spec_path)
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


def identity(v):
  return v


def addresses_from_address_families(address_families):
  """Given a list of AddressFamilies, return an Addresses object containing all addressables."""
  return Addresses(tuple(a for af in address_families for a in af.addressables.keys()))


def filter_build_dirs(address_mapper, snapshot):
  """Given a Snapshot matching a build pattern, return parent directories as BuildDirs."""
  dirnames = set(dirname(f.stat.path) for f in snapshot.files)
  ignored_dirnames = address_mapper.build_ignore_patterns.match_files('{}/'.format(dirname) for dirname in dirnames)
  ignored_dirnames = set(d.rstrip('/') for d in ignored_dirnames)
  return BuildDirs(tuple(Dir(d) for d in dirnames if d not in ignored_dirnames))


def single_or_sib_addresses_to_globs(address_mapper, single_or_sib_addresses):
  """Given a SiblingAddresses or SingleAddress object, return a PathGlobs object for relevant build files."""
  patterns = address_mapper.build_patterns
  return PathGlobs.create(single_or_sib_addresses.directory, include=patterns, exclude=[])


def descendant_addresses_to_globs(address_mapper, descendant_addresses):
  """Given a DescendantAddresses object, return a PathGlobs object for matching build files."""
  patterns = [join('**', pattern) for pattern in address_mapper.build_patterns]
  return PathGlobs.create(descendant_addresses.directory, include=patterns, exclude=[])


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


def ascendant_addresses_to_globs(address_mapper, ascendant_addresses):
  """Given an AscendantAddresses object, return a PathGlobs object for matching build files."""
  patterns = [
    join(f, pattern)
    for pattern in address_mapper.build_patterns
    for f in _recursive_dirname(ascendant_addresses.directory)
  ]
  return PathGlobs.create('', include=patterns, exclude=[])


def create_graph_tasks(address_mapper, symbol_table_cls):
  """Creates tasks used to parse Structs from BUILD files.

  :param address_mapper_key: The subject key for an AddressMapper instance.
  :param symbol_table_cls: A SymbolTable class to provide symbols for Address lookups.
  """
  symbol_table_constraint = symbol_table_cls.constraint()
  return [
    # Support for resolving Structs from Addresses
    (symbol_table_constraint,
     [Select(UnhydratedStruct),
      SelectDependencies(
        symbol_table_constraint, UnhydratedStruct, field_types=(Address,))],
      hydrate_struct),
    (UnhydratedStruct,
     [SelectProjection(AddressFamily, Dir, ('spec_path',), Exactly(Address, BuildFileAddress)),
      Select(Exactly(Address, BuildFileAddress))],
     resolve_unhydrated_struct),
  ] + [
    # BUILD file parsing.
    (AddressFamily,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(Dir),
      SelectProjection(FilesContent, PathGlobs, ('path_globs',), BuildFiles)],
     parse_address_family),
    (BuildFiles,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(DirectoryListing)],
     filter_buildfile_paths),
  ] + [
    # Spec handling: locate directories that contain build files, and request
    # AddressFamilies for each of them.
    (Addresses,
     [SelectDependencies(AddressFamily, BuildDirs, field_types=(Dir,))],
     addresses_from_address_families),
    (BuildDirs,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(Snapshot)],
     filter_build_dirs),
    (PathGlobs,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(SiblingAddresses)],
     single_or_sib_addresses_to_globs),
    (PathGlobs,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(SingleAddress)],
     single_or_sib_addresses_to_globs),
    (PathGlobs,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(DescendantAddresses)],
     descendant_addresses_to_globs),
    (PathGlobs,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(AscendantAddresses)],
     ascendant_addresses_to_globs),
  ]
