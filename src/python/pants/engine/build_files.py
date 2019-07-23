# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from collections.abc import MutableMapping, MutableSequence
from os.path import dirname, join

from twitter.common.collections import OrderedSet

from pants.base.project_tree import Dir
from pants.base.specs import SingleAddress, Spec, Specs
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.engine.addressable import AddressableDescriptor, BuildFileAddresses
from pants.engine.fs import Digest, FilesContent, PathGlobs, Snapshot
from pants.engine.mapper import AddressFamily, AddressMap, AddressMapper, ResolveError
from pants.engine.objects import Locatable, SerializableFactory, Validatable
from pants.engine.parser import HydratedStruct
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.engine.struct import Struct
from pants.util.objects import TypeConstraintError


logger = logging.getLogger(__name__)


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


def _key_func(entry):
  key, value = entry
  return key


@rule(AddressFamily, [AddressMapper, Dir])
def parse_address_family(address_mapper, directory):
  """Given an AddressMapper and a directory, return an AddressFamily.

  The AddressFamily may be empty, but it will not be None.
  """
  patterns = tuple(join(directory.path, p) for p in address_mapper.build_patterns)
  path_globs = PathGlobs(include=patterns,
                         exclude=address_mapper.build_ignore_patterns)
  snapshot = yield Get(Snapshot, PathGlobs, path_globs)
  files_content = yield Get(FilesContent, Digest, snapshot.directory_digest)

  if not files_content:
    raise ResolveError('Directory "{}" does not contain any BUILD files.'.format(directory.path))
  address_maps = []
  for filecontent_product in files_content:
    address_maps.append(AddressMap.parse(filecontent_product.path,
                                         filecontent_product.content,
                                         address_mapper.parser))
  yield AddressFamily.create(directory.path, address_maps)


def _raise_did_you_mean(address_family, name, source=None):
  names = [a.target_name for a in address_family.addressables]
  possibilities = '\n  '.join(':{}'.format(target_name) for target_name in sorted(names))

  resolve_error = ResolveError('"{}" was not found in namespace "{}". '
                               'Did you mean one of:\n  {}'
                               .format(name, address_family.namespace, possibilities))

  if source:
    raise resolve_error from source
  else:
    raise resolve_error


@rule(HydratedStruct, [AddressMapper, Address])
def hydrate_struct(address_mapper, address):
  """Given an AddressMapper and an Address, resolve a Struct from a BUILD file.

  Recursively collects any embedded addressables within the Struct, but will not walk into a
  dependencies field, since those should be requested explicitly by rules.
  """

  address_family = yield Get(AddressFamily, Dir(address.spec_path))

  struct = address_family.addressables.get(address)
  addresses = address_family.addressables
  if not struct or address not in addresses:
    _raise_did_you_mean(address_family, address.target_name)
  # TODO: This is effectively: "get the BuildFileAddress for this Address".
  #  see https://github.com/pantsbuild/pants/issues/6657
  address = next(build_address for build_address in addresses if build_address == address)

  inline_dependencies = []
  def maybe_append(outer_key, value):
    if isinstance(value, str):
      if outer_key != 'dependencies':
        inline_dependencies.append(Address.parse(value,
                                          relative_to=address.spec_path,
                                          subproject_roots=address_mapper.subproject_roots))
    elif isinstance(value, Struct):
      collect_inline_dependencies(value)

  def collect_inline_dependencies(item):
    for key, value in sorted(item._asdict().items(), key=_key_func):
      if not AddressableDescriptor.is_addressable(item, key):
        continue
      if isinstance(value, MutableMapping):
        for _, v in sorted(value.items(), key=_key_func):
          maybe_append(key, v)
      elif isinstance(value, MutableSequence):
        for v in value:
          maybe_append(key, v)
      else:
        maybe_append(key, value)

  # Recursively collect inline dependencies from the fields of the struct into `inline_dependencies`.
  collect_inline_dependencies(struct)

  # And then hydrate the inline dependencies.
  hydrated_inline_dependencies = yield [Get(HydratedStruct, Address, a) for a in inline_dependencies]
  dependencies = [d.value for d in hydrated_inline_dependencies]

  def maybe_consume(outer_key, value):
    if isinstance(value, str):
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

      if isinstance(value, MutableMapping):
        container_type = type(value)
        hydrated_args[key] = container_type((k, maybe_consume(key, v))
                                            for k, v in sorted(value.items(), key=_key_func))
      elif isinstance(value, MutableSequence):
        container_type = type(value)
        hydrated_args[key] = container_type(maybe_consume(key, v) for v in value)
      else:
        hydrated_args[key] = maybe_consume(key, value)
    return _hydrate(type(item), address.spec_path, **hydrated_args)

  yield HydratedStruct(consume_dependencies(struct, args={'address': address}))


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


@rule(BuildFileAddresses, [AddressMapper, Specs])
def addresses_from_address_families(address_mapper, specs):
  """Given an AddressMapper and list of Specs, return matching BuildFileAddresses.

  :raises: :class:`ResolveError` if:
     - there were no matching AddressFamilies, or
     - the Spec matches no addresses for SingleAddresses.
  :raises: :class:`AddressLookupError` if no targets are matched for non-SingleAddress specs.
  """
  # Capture a Snapshot covering all paths for these Specs, then group by directory.
  snapshot = yield Get(Snapshot, PathGlobs, _spec_to_globs(address_mapper, specs))
  dirnames = {dirname(f) for f in snapshot.files}
  address_families = yield [Get(AddressFamily, Dir(d)) for d in dirnames]
  address_family_by_directory = {af.namespace: af for af in address_families}

  matched_addresses = OrderedSet()
  for spec in specs:
    # NB: if a spec is provided which expands to some number of targets, but those targets match
    # --exclude-target-regexp, we do NOT fail! This is why we wait to apply the tag and exclude
    # patterns until we gather all the targets the spec would have matched without them.
    try:
      addr_families_for_spec = spec.matching_address_families(address_family_by_directory)
    except Spec.AddressFamilyResolutionError as e:
      raise ResolveError(e) from e

    try:
      all_addr_tgt_pairs = spec.address_target_pairs_from_address_families(addr_families_for_spec)
    except Spec.AddressResolutionError as e:
      raise AddressLookupError(e) from e
    except SingleAddress._SingleAddressResolutionError as e:
      _raise_did_you_mean(e.single_address_family, e.name, source=e)

    matched_addresses.update(
      addr for (addr, tgt) in all_addr_tgt_pairs
      if specs.matcher.matches_target_address_pair(addr, tgt)
    )

  # NB: This may be empty, as the result of filtering by tag and exclude patterns!
  yield BuildFileAddresses(tuple(matched_addresses))


def _spec_to_globs(address_mapper, specs):
  """Given a Specs object, return a PathGlobs object for the build files that it matches."""
  patterns = set()
  for spec in specs:
    patterns.update(spec.make_glob_patterns(address_mapper))
  return PathGlobs(include=patterns, exclude=address_mapper.build_ignore_patterns)


def create_graph_rules(address_mapper):
  """Creates tasks used to parse Structs from BUILD files.

  :param address_mapper_key: The subject key for an AddressMapper instance.
  :param symbol_table: A SymbolTable instance to provide symbols for Address lookups.
  """

  @rule(AddressMapper, [])
  def address_mapper_singleton():
    return address_mapper

  return [
    address_mapper_singleton,
    # BUILD file parsing.
    hydrate_struct,
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
