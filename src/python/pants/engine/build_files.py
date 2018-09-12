# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import functools
import logging
import re
from builtins import next, str
from os.path import dirname, join

import six

from pants.base.project_tree import Dir
from pants.base.specs import SingleAddress, Spec, Specs
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.engine.addressable import AddressableDescriptor, BuildFileAddresses
from pants.engine.fs import DirectoryDigest, FilesContent, PathGlobs, Snapshot
from pants.engine.mapper import AddressFamily, AddressMap, AddressMapper, ResolveError
from pants.engine.objects import Locatable, SerializableFactory, Validatable
from pants.engine.rules import RootRule, SingletonRule, TaskRule, rule
from pants.engine.selectors import Get, Select
from pants.engine.struct import Struct
from pants.util.filtering import create_filters, wrap_filters
from pants.util.memo import memoized_property
from pants.util.objects import TypeConstraintError, datatype


logger = logging.getLogger(__name__)


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
  path_globs = PathGlobs(include=patterns,
                         exclude=address_mapper.build_ignore_patterns)
  snapshot = yield Get(Snapshot, PathGlobs, path_globs)
  files_content = yield Get(FilesContent, DirectoryDigest, snapshot.directory_digest)

  if not files_content:
    raise ResolveError('Directory "{}" does not contain any BUILD files.'.format(directory.path))
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
    next(build_address for build_address in addresses if build_address == address),
    struct,
    dependencies)


def hydrate_struct(symbol_table_constraint, address_mapper, unhydrated_struct):
  """Hydrates a Struct from an UnhydratedStruct and its satisfied embedded addressable deps.

  Note that this relies on the guarantee that DependenciesNode provides dependencies in the
  order they were requested.
  """
  dependencies = yield [Get(symbol_table_constraint, Address, a) for a in unhydrated_struct.dependencies]
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

  yield consume_dependencies(struct, args={'address': address})


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


class _MappedSpecs(datatype([
    ('address_families', tuple),
    ('specs', Specs),
])):
  """Wraps up logic to resolve specs into individual target addresses, or error out."""

  def __new__(cls, address_families, specs):
    return super(_MappedSpecs, cls).__new__(cls, tuple(address_families), specs)

  @memoized_property
  def _exclude_compiled_regexps(self):
    return [re.compile(pattern) for pattern in set(self.specs.exclude_patterns or [])]

  def _excluded_by_pattern(self, address):
    return any(p.search(address.spec) is not None for p in self._exclude_compiled_regexps)

  @memoized_property
  def _target_tag_matches(self):
    def filter_for_tag(tag):
      return lambda t: tag in [str(t_tag) for t_tag in t.kwargs().get("tags", [])]
    return wrap_filters(create_filters(self.specs.tags, filter_for_tag))

  def _matches_target_address_pair(self, address, target):
    return self._target_tag_matches(target) and not self._excluded_by_pattern(address)

  @memoized_property
  def _address_family_by_directory(self):
    return {af.namespace: af for af in self.address_families}

  def _matching_addresses_for_spec(self, spec):
    # NB: if a spec is provided which expands to some number of targets, but those targets match
    # --exclude-target-regexp, we do NOT fail! This is why we wait to apply the tag and exclude
    # patterns until we gather all the targets the spec would have matched without them.
    try:
      addr_families_for_spec = spec.matching_address_families(self._address_family_by_directory)
    except Spec.AddressFamilyResolutionError as e:
      raise ResolveError(e)

    try:
      all_addr_tgt_pairs = spec.address_target_pairs_from_address_families(addr_families_for_spec)
    except Spec.AddressResolutionError as e:
      raise AddressLookupError(e)
    except SingleAddress.SingleAddressResolutionError as e:
      _raise_did_you_mean(e.single_address_family, e.name)

    all_matching_addresses = [
      addr for (addr, tgt) in all_addr_tgt_pairs
      if self._matches_target_address_pair(addr, tgt)
    ]
    # NB: This may be empty, as the result of filtering by tag and exclude patterns!
    return all_matching_addresses

  def all_matching_addresses(self):
    """Return all addresses the given specs resolve to, within the given address families.

    :raises: :class:`ResolveError` if:
     - there were no matching AddressFamilies, or
     - the Spec matches no addresses for SingleAddresses.
    :raises: :class:`AddressLookupError` if no targets are matched for non-SingleAddress specs.
    """
    matched_addresses = []
    for spec in self.specs.dependencies:
      matched_addresses.extend(self._matching_addresses_for_spec(spec))
    return matched_addresses


@rule(BuildFileAddresses, [Select(AddressMapper), Select(Specs)])
def addresses_from_address_families(address_mapper, specs):
  """Given an AddressMapper and list of Specs, return matching BuildFileAddresses.

  :raises: :class:`ResolveError` if:
     - there were no matching AddressFamilies, or
     - the Spec matches no addresses for SingleAddresses.
  :raises: :class:`AddressLookupError` if no targets are matched for non-SingleAddress specs.
  """
  # Capture a Snapshot covering all paths for these Specs, then group by directory.
  snapshot = yield Get(Snapshot, PathGlobs, _spec_to_globs(address_mapper, specs))
  dirnames = {dirname(f.stat.path) for f in snapshot.files}
  address_families = yield [Get(AddressFamily, Dir(d)) for d in dirnames]

  # all_matching_addresses() could be a free function as well -- it just seemed to make it easier to
  # follow to package it up into a datatype here.
  mapped_specs = _MappedSpecs(address_families, specs)
  deduplicated_addresses = frozenset(mapped_specs.all_matching_addresses())

  yield BuildFileAddresses(tuple(deduplicated_addresses))


def _spec_to_globs(address_mapper, specs):
  """Given a Specs object, return a PathGlobs object for the build files that it matches."""
  patterns = set()
  for spec in specs.dependencies:
    patterns.update(spec.make_glob_patterns(address_mapper))
  return PathGlobs(include=patterns, exclude=address_mapper.build_ignore_patterns)


def create_graph_rules(address_mapper, symbol_table):
  """Creates tasks used to parse Structs from BUILD files.

  :param address_mapper_key: The subject key for an AddressMapper instance.
  :param symbol_table: A SymbolTable instance to provide symbols for Address lookups.
  """
  symbol_table_constraint = symbol_table.constraint()

  partial_hydrate_struct = functools.partial(hydrate_struct, symbol_table_constraint)
  partial_hydrate_struct.__name__ = 'hydrate_struct'

  return [
    # A singleton to provide the AddressMapper.
    SingletonRule(AddressMapper, address_mapper),
    # Support for resolving Structs from Addresses.
    TaskRule(
      symbol_table_constraint,
      [Select(AddressMapper),
       Select(UnhydratedStruct)],
      partial_hydrate_struct,
      input_gets=[Get(symbol_table_constraint, Address)],
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
