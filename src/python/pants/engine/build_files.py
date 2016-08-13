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
from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import AddressableDescriptor, Addresses, TypeConstraintError
from pants.engine.fs import DirectoryListing, Files, FilesContent, Path, PathGlobs
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


class BuildFiles(datatype('BuildFiles', ['files'])):
  """A list of Paths that are known to match a build file pattern."""


def filter_buildfile_paths(address_mapper, directory_listing):
  if not directory_listing.exists:
    raise ResolveError('Directory "{}" does not exist.'.format(directory_listing.directory.path))

  build_pattern = address_mapper.build_pattern
  def match(stat):
    return type(stat) is File and fnmatch(basename(stat.path), build_pattern)
  build_files = tuple(Path(stat.path, stat)
                      for stat in directory_listing.dependencies if match(stat))
  return BuildFiles(build_files)


def parse_address_family(address_mapper, path, build_files_content):
  """Given the contents of the build files in one directory, return an AddressFamily.

  The AddressFamily may be empty, but it will not be None.
  """
  if not build_files_content.dependencies:
    raise ResolveError('Directory "{}" does not contain build files.'.format(path))
  address_maps = []
  for filepath, filecontent in build_files_content.dependencies:
    address_maps.append(AddressMap.parse(filepath,
                                         filecontent,
                                         address_mapper.symbol_table_cls,
                                         address_mapper.parser_cls))
  return AddressFamily.create(path.path, address_maps)


class UnhydratedStruct(datatype('UnhydratedStruct', ['address', 'struct', 'dependencies'])):
  """A product type that holds a Struct which has not yet been hydrated.

  A Struct counts as "hydrated" when all of its members (which are not themselves dependencies
  lists) have been resolved from the graph. This means that hyrating a struct is eager in terms
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
  if not struct:
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
  return UnhydratedStruct(address, struct, dependencies)


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


def address_from_address_family(address_family, single_address):
  """Given an AddressFamily and a SingleAddress, return an Addresses object containing the Address.

  Raises an exception if the SingleAddress does not match an existing Address.
  """
  name = single_address.name
  if name is None:
    name = basename(single_address.directory)
  if name not in address_family.objects_by_name:
    _raise_did_you_mean(address_family, single_address.name)
  return Addresses(tuple([Address(address_family.namespace, name)]))


def addresses_from_address_family(address_family):
  """Given an AddressFamily, return an Addresses objects containing all of its `addressables`."""
  return Addresses(tuple(address_family.addressables.keys()))


def addresses_from_address_families(address_families):
  """Given a list of AddressFamilies, return an Addresses object containing all addressables."""
  return Addresses(tuple(a for af in address_families for a in af.addressables.keys()))


def filter_build_dirs(build_files):
  """Given Files matching a build pattern, return their parent directories as BuildDirs."""
  dirnames = set(dirname(f.stat.path) for f in build_files.dependencies)
  return BuildDirs(tuple(Dir(d) for d in dirnames))


def descendant_addresses_to_globs(address_mapper, descendant_addresses):
  """Given a DescendantAddresses object, return a PathGlobs object for matching build files.
  
  This allows us to limit our AddressFamily requests to directories that contain build files.
  """

  pattern = address_mapper.build_pattern
  return PathGlobs.create_from_specs(descendant_addresses.directory, [pattern, join('**', pattern)])


def create_graph_tasks(address_mapper, symbol_table_cls):
  """Creates tasks used to parse Structs from BUILD files.

  :param address_mapper_key: The subject key for an AddressMapper instance.
  :param symbol_table_cls: A SymbolTable class to provide symbols for Address lookups.
  """
  return [
    # Support for resolving Structs from Addresses
    (Struct,
     [Select(UnhydratedStruct),
      SelectDependencies(Struct, UnhydratedStruct)],
     hydrate_struct),
    (UnhydratedStruct,
     [SelectProjection(AddressFamily, Dir, ('spec_path',), Address),
      Select(Address)],
     resolve_unhydrated_struct),
  ] + [
    # BUILD file parsing.
    (AddressFamily,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(Dir),
      SelectProjection(FilesContent, Files, ('files',), BuildFiles)],
     parse_address_family),
    (BuildFiles,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(DirectoryListing)],
     filter_buildfile_paths),
  ] + [
    # Addresses for user-defined products might possibly be resolvable from BLD files. These tasks
    # define that lookup for each literal product.
    (product,
     [Select(Struct)],
     identity)
    for product in symbol_table_cls.table().values() if product is not Struct
  ] + [
    # Simple spec handling.
    (Addresses,
     [SelectProjection(AddressFamily, Dir, ('directory',), SingleAddress),
      Select(SingleAddress)],
     address_from_address_family),
    (Addresses,
     [SelectProjection(AddressFamily, Dir, ('directory',), SiblingAddresses)],
     addresses_from_address_family),
  ] + [
    # Recursive spec handling: locate directories that contain build files, and request
    # AddressFamilies for each of them.
    (Addresses,
     [SelectDependencies(AddressFamily, BuildDirs)],
     addresses_from_address_families),
    (BuildDirs,
     [Select(Files)],
     filter_build_dirs),
    (PathGlobs,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(DescendantAddresses)],
     descendant_addresses_to_globs),
  ]
