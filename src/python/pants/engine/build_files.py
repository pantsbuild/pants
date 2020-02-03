# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from collections.abc import MutableMapping, MutableSequence
from dataclasses import dataclass
from typing import Dict

from twitter.common.collections import OrderedSet

from pants.base.project_tree import Dir
from pants.base.specs import AddressSpec, AddressSpecs, SingleAddress, Spec, more_specific
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.engine.addressable import (
  AddressableDescriptor,
  BuildFileAddresses,
  ProvenancedBuildFileAddress,
  ProvenancedBuildFileAddresses,
)
from pants.engine.fs import Digest, FilesContent, PathGlobs, Snapshot
from pants.engine.mapper import AddressFamily, AddressMap, AddressMapper, ResolveError
from pants.engine.objects import Locatable, SerializableFactory, Validatable
from pants.engine.parser import HydratedStruct
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.struct import Struct
from pants.util.objects import TypeConstraintError


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


def _key_func(entry):
  key, value = entry
  return key


@rule
async def parse_address_family(address_mapper: AddressMapper, directory: Dir) -> AddressFamily:
  """Given an AddressMapper and a directory, return an AddressFamily.

  The AddressFamily may be empty, but it will not be None.
  """
  path_globs = PathGlobs(
    globs=(
      *(os.path.join(directory.path, p) for p in address_mapper.build_patterns),
      *(f"!{p}" for p in address_mapper.build_ignore_patterns),
    )
  )
  snapshot = await Get[Snapshot](PathGlobs, path_globs)
  files_content = await Get[FilesContent](Digest, snapshot.directory_digest)

  if not files_content:
    raise ResolveError(
      'Directory "{}" does not contain any BUILD files.'.format(directory.path)
    )
  address_maps = []
  for filecontent_product in files_content:
    address_maps.append(
      AddressMap.parse(
        filecontent_product.path, filecontent_product.content, address_mapper.parser
      )
    )
  return AddressFamily.create(directory.path, address_maps)


def _raise_did_you_mean(address_family: AddressFamily, name: str, source=None) -> None:
  names = [a.target_name for a in address_family.addressables]
  possibilities = "\n  ".join(":{}".format(target_name) for target_name in sorted(names))

  resolve_error = ResolveError(
    '"{}" was not found in namespace "{}". '
    "Did you mean one of:\n  {}".format(name, address_family.namespace, possibilities)
  )

  if source:
    raise resolve_error from source
  raise resolve_error


@rule
async def hydrate_struct(address_mapper: AddressMapper, address: Address) -> HydratedStruct:
  """Given an AddressMapper and an Address, resolve a Struct from a BUILD file.

  Recursively collects any embedded addressables within the Struct, but will not walk into a
  dependencies field, since those should be requested explicitly by rules.
  """

  address_family = await Get[AddressFamily](Dir(address.spec_path))

  # NB: `address_family.addressables` is a dictionary of `BuildFileAddress`es and we look it up
  # with an `Address`. This works because `BuildFileAddress` is a subclass, but MyPy warns that it
  # could be a bug.
  struct = address_family.addressables.get(address)  # type: ignore[call-overload]
  addresses = address_family.addressables
  if not struct or address not in addresses:
    _raise_did_you_mean(address_family, address.target_name)
  # TODO: This is effectively: "get the BuildFileAddress for this Address".
  #  see https://github.com/pantsbuild/pants/issues/6657
  address = next(build_address for build_address in addresses if build_address == address)

  inline_dependencies = []

  def maybe_append(outer_key, value):
    if isinstance(value, str):
      if outer_key != "dependencies":
        inline_dependencies.append(
          Address.parse(
            value,
            relative_to=address.spec_path,
            subproject_roots=address_mapper.subproject_roots,
          )
        )
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
  hydrated_inline_dependencies = await MultiGet(Get[HydratedStruct](Address, a)
                                                for a in inline_dependencies)
  dependencies = [d.value for d in hydrated_inline_dependencies]

  def maybe_consume(outer_key, value):
    if isinstance(value, str):
      if outer_key == "dependencies":
        # Don't recurse into the dependencies field of a Struct, since those will be explicitly
        # requested by tasks. But do ensure that their addresses are absolute, since we're
        # about to lose the context in which they were declared.
        value = Address.parse(
          value,
          relative_to=address.spec_path,
          subproject_roots=address_mapper.subproject_roots,
        )
      else:
        value = dependencies[maybe_consume.idx]
        maybe_consume.idx += 1
    elif isinstance(value, Struct):
      value = consume_dependencies(value)
    return value

  # NB: Some pythons throw an UnboundLocalError for `idx` if it is a simple local variable.
  # TODO(#8496): create a decorator for functions which declare a sentinel variable like this!
  maybe_consume.idx = 0         # type: ignore[attr-defined]

  # 'zip' the previously-requested dependencies back together as struct fields.
  def consume_dependencies(item, args=None):
    hydrated_args = args or {}
    for key, value in sorted(item._asdict().items(), key=_key_func):
      if not AddressableDescriptor.is_addressable(item, key):
        hydrated_args[key] = value
        continue

      if isinstance(value, MutableMapping):
        container_type = type(value)
        hydrated_args[key] = container_type(
          (k, maybe_consume(key, v)) for k, v in sorted(value.items(), key=_key_func)
        )
      elif isinstance(value, MutableSequence):
        container_type = type(value)
        hydrated_args[key] = container_type(maybe_consume(key, v) for v in value)
      else:
        hydrated_args[key] = maybe_consume(key, value)
    return _hydrate(type(item), address.spec_path, **hydrated_args)

  return HydratedStruct(consume_dependencies(struct, args={"address": address}))


def _hydrate(item_type, spec_path, **kwargs):
  # If the item will be Locatable, inject the spec_path.
  if issubclass(item_type, Locatable):
    kwargs["spec_path"] = spec_path

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


@rule
async def provenanced_addresses_from_address_families(
  address_mapper: AddressMapper, address_specs: AddressSpecs,
) -> ProvenancedBuildFileAddresses:
  """Given an AddressMapper and list of AddressSpecs, return matching ProvenancedBuildFileAddresses.

  :raises: :class:`ResolveError` if:
     - there were no matching AddressFamilies, or
     - the AddressSpec matches no addresses for SingleAddresses.
  :raises: :class:`AddressLookupError` if no targets are matched for non-SingleAddress specs.
  """
  # Capture a Snapshot covering all paths for these AddressSpecs, then group by directory.
  snapshot = await Get[Snapshot](PathGlobs, _address_spec_to_globs(address_mapper, address_specs))
  dirnames = {os.path.dirname(f) for f in snapshot.files}
  address_families = await MultiGet(Get[AddressFamily](Dir(d)) for d in dirnames)
  address_family_by_directory = {af.namespace: af for af in address_families}

  matched_addresses = OrderedSet()
  addr_to_provenance: Dict[BuildFileAddress, AddressSpec] = {}

  for address_spec in address_specs:
    # NB: if an address spec is provided which expands to some number of targets, but those targets
    # match --exclude-target-regexp, we do NOT fail! This is why we wait to apply the tag and
    # exclude patterns until we gather all the targets the address spec would have matched
    # without them.
    try:
      addr_families_for_spec = address_spec.matching_address_families(address_family_by_directory)
    except AddressSpec.AddressFamilyResolutionError as e:
      raise ResolveError(e) from e

    try:
      all_addr_tgt_pairs = address_spec.address_target_pairs_from_address_families(
        addr_families_for_spec
      )
      for addr, _ in all_addr_tgt_pairs:
        # A target might be covered by multiple specs, so we take the most specific one.
        addr_to_provenance[addr] = more_specific(addr_to_provenance.get(addr), address_spec)
    except AddressSpec.AddressResolutionError as e:
      raise AddressLookupError(e) from e
    except SingleAddress._SingleAddressResolutionError as e:
      _raise_did_you_mean(e.single_address_family, e.name, source=e)

    matched_addresses.update(
      addr
      for (addr, tgt) in all_addr_tgt_pairs
      if address_specs.matcher.matches_target_address_pair(addr, tgt)
    )

  # NB: This may be empty, as the result of filtering by tag and exclude patterns!
  return ProvenancedBuildFileAddresses(
    ProvenancedBuildFileAddress(build_file_address=addr, provenance=addr_to_provenance[addr])
    for addr in matched_addresses
  )


@rule
def remove_provenance(pbfas: ProvenancedBuildFileAddresses) -> BuildFileAddresses:
  return BuildFileAddresses(pbfa.build_file_address for pbfa in pbfas)


@dataclass(frozen=True)
class AddressProvenanceMap:
  bfaddr_to_spec: Dict[BuildFileAddress, Spec]

  def is_single_address(self, address: BuildFileAddress) -> bool:
    return isinstance(self.bfaddr_to_spec.get(address), SingleAddress)


@rule
def address_provenance_map(pbfas: ProvenancedBuildFileAddresses) -> AddressProvenanceMap:
  return AddressProvenanceMap(
    bfaddr_to_spec={pbfa.build_file_address: pbfa.provenance for pbfa in pbfas.dependencies}
  )


def _address_spec_to_globs(address_mapper: AddressMapper, address_specs: AddressSpecs) -> PathGlobs:
  """Given an AddressSpecs object, return a PathGlobs object for the build files that it matches."""
  patterns = set()
  for address_spec in address_specs:
    patterns.update(address_spec.make_glob_patterns(address_mapper))
  return PathGlobs(globs=(*patterns, *(f"!{p}" for p in address_mapper.build_ignore_patterns)))


def create_graph_rules(address_mapper: AddressMapper):
  """Creates tasks used to parse Structs from BUILD files."""

  @rule
  def address_mapper_singleton() -> AddressMapper:
    return address_mapper

  return [
    address_mapper_singleton,
    # BUILD file parsing.
    hydrate_struct,
    parse_address_family,
    # AddressSpec handling: locate directories that contain build files, and request
    # AddressFamilies for each of them.
    provenanced_addresses_from_address_families,
    remove_provenance,
    address_provenance_map,
    # Root rules representing parameters that might be provided via root subjects.
    RootRule(Address),
    RootRule(BuildFileAddress),
    RootRule(BuildFileAddresses),
    RootRule(AddressSpecs),
  ]
