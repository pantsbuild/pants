# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.exp.addressable import Addresses
from pants.engine.exp.fs import (DirectoryListing, FileContent, FilesContent, Path, PathDirWildcard,
                                 PathGlobs, Paths, PathWildcard, RecursiveSubDirectories,
                                 files_content, filter_dir_listing, filter_file_listing,
                                 merge_paths, recursive_subdirectories)
from pants.engine.exp.graph import (BuildFilePaths, UnhydratedStruct, address_from_address_family,
                                    addresses_from_address_families, addresses_from_address_family,
                                    filter_buildfile_paths, hydrate_struct, identity,
                                    parse_address_family, resolve_unhydrated_struct)
from pants.engine.exp.mapper import AddressFamily, AddressMapper
from pants.engine.exp.selectors import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants.engine.exp.struct import Struct


# TODO: The approach to task registration needs iteration - but for now, this file acts as a quick
# and dirty unified placeholder for the existing experimental-mode approach.
def create_fs_tasks():
  """Creates tasks that consume the native filesystem Node type."""
  return [
    (RecursiveSubDirectories,
     [Select(Path),
      SelectDependencies(RecursiveSubDirectories, DirectoryListing, field='directories')],
     recursive_subdirectories),
    (Paths,
     [SelectDependencies(Paths, PathGlobs)],
     merge_paths),
    (Paths,
     [SelectProjection(DirectoryListing, Path, ('directory',), PathWildcard),
      Select(PathWildcard)],
     filter_file_listing),
    (PathGlobs,
     [SelectProjection(DirectoryListing, Path, ('directory',), PathDirWildcard),
      Select(PathDirWildcard)],
     filter_dir_listing),
    (FilesContent,
     [SelectDependencies(FileContent, Paths)],
     files_content),
  ]


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
     [SelectProjection(AddressFamily, Path, ('spec_path',), Address),
      Select(Address)],
     resolve_unhydrated_struct),
  ] + [
    # BUILD file parsing.
    (AddressFamily,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(Path),
      SelectProjection(FilesContent, Paths, ('paths',), BuildFilePaths)],
     parse_address_family),
    (BuildFilePaths,
     [SelectLiteral(address_mapper, AddressMapper),
      Select(DirectoryListing)],
     filter_buildfile_paths),
  ] + [
    # Addresses for user-defined products might possibly be resolvable from BLD files. These tasks
    # define that lookup for each literal product.
    (product,
     [Select(Struct)],
     identity)
    for product in symbol_table_cls.table().values()
  ] + [
    # Spec handling.
    (Addresses,
     [SelectProjection(AddressFamily, Path, ('directory',), SingleAddress),
      Select(SingleAddress)],
     address_from_address_family),
    (Addresses,
     [SelectProjection(AddressFamily, Path, ('directory',), SiblingAddresses)],
     addresses_from_address_family),
    (Addresses,
     [SelectDependencies(AddressFamily, RecursiveSubDirectories)],
     addresses_from_address_families),
    # TODO: This is a workaround for the fact that we can't currently "project" in a
    # SelectDependencies clause: we launch the recursion by requesting RecursiveSubDirectories
    # for a Directory projected from DescendantAddresses.
    (RecursiveSubDirectories,
     [SelectProjection(RecursiveSubDirectories, Path, ('directory',), DescendantAddresses)],
     identity),
  ]
