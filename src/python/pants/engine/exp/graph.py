# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections

import six

from pants.build_graph.address import Address
from pants.engine.exp.addressable import (AddressableDescriptor, Directory, StructAddress,
                                          TypeConstraintError)
from pants.engine.exp.mapper import AddressFamily, AddressMapper, ResolveError
from pants.engine.exp.objects import SerializableFactory, Validatable, datatype
from pants.engine.exp.scheduler import Select, SelectDependencies, SelectLiteral, SelectProjection
from pants.engine.exp.struct import Struct


class ResolvedTypeMismatchError(ResolveError):
  """Indicates a resolved object was not of the expected type."""


def _key_func(entry):
  key, value = entry
  return key


def parse_address_family(address_mapper, directory):
  """Given the spec path for an Address, parses and returns its AddressFamily."""
  # TODO: break up AddressMapper rather than using private APIs
  family = address_mapper._maybe_family(directory.path)
  if not family:
    raise ResolveError('No addresses registered in {}'.format(directory))
  return family


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


def resolve_unhydrated_struct(address_family, struct_address):
  """Given a StructAddress and its AddressFamily, resolve an UnhydratedStruct.

  Recursively collects any embedded addressables within the Struct, but will not walk into a
  dependencies field, since those are requested explicitly by tasks using SelectDependencies.
  """

  address = Address(struct_address.spec_path, struct_address.name)
  struct = address_family.addressables.get(address)
  if not struct:
    possibilities = '\n  '.join(str(a) for a in address_family.addressables)
    raise ResolveError('A Struct was not found at address {}. '
                       'Did you mean one of?:\n  {}'.format(address, possibilities))

  dependencies = []
  def maybe_append(outer_key, value):
    if isinstance(value, six.string_types):
      if outer_key != 'dependencies':
        dep_address = Address.parse(value, relative_to=address.spec_path)
        dependencies.append(StructAddress(dep_address.spec_path, dep_address.target_name))
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
    return _hydrate(type(item), **hydrated_args)

  return consume_dependencies(struct, args={'address': address})


def _hydrate(item_type, **kwargs):
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


def create_graph_tasks(address_mapper):
  """Given an AddressMapper, creates tasks used to parse Structs from BUILD files."""
  return [
    (Struct,
      [Select(UnhydratedStruct),
       SelectDependencies(Struct, UnhydratedStruct)],
      hydrate_struct),
    (UnhydratedStruct,
      [SelectProjection(AddressFamily, Directory, 'spec_path', StructAddress),
       Select(StructAddress)],
      resolve_unhydrated_struct),
    (AddressFamily,
      [SelectLiteral(address_mapper, AddressMapper),
       Select(Directory)],
      parse_address_family),
  ]
