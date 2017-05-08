# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import traceback

from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target import Target


logger = logging.getLogger(__name__)


class MutableBuildGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected."""

  def __init__(self, address_mapper):
    self._address_mapper = address_mapper
    super(MutableBuildGraph, self).__init__()

  def clone_new(self):
    """Returns a new BuildGraph instance of the same type and with the same __init__ params."""
    return MutableBuildGraph(self._address_mapper)

  def reset(self):
    super(MutableBuildGraph, self).reset()
    self._addresses_already_closed = set()

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    target = target_type(name=address.target_name,
                         address=address,
                         build_graph=self,
                         **kwargs)
    self.inject_target(target,
                       dependencies=dependencies,
                       derived_from=derived_from,
                       synthetic=True)

  def inject_address_closure(self, address):
    if self.contains_address(address):
      # The address was either mapped in or synthetically injected already.
      return

    if address in self._addresses_already_closed:
      # We've visited this address already in the course of the active recursive injection.
      return

    mapper = self._address_mapper

    target_address, target_addressable = mapper.resolve(address)

    self._addresses_already_closed.add(target_address)
    try:
      dep_addresses = list(mapper.specs_to_addresses(target_addressable.dependency_specs,
                                                     relative_to=target_address.spec_path))
      deps_seen = set()
      for dep_address in dep_addresses:
        if dep_address in deps_seen:
          raise self.DuplicateAddressError(
            'Addresses in dependencies must be unique. \'{spec}\' is referenced more than once.'
            .format(spec=dep_address.spec))
        deps_seen.add(dep_address)
        self.inject_address_closure(dep_address)

      if not self.contains_address(target_address):
        target = self._target_addressable_to_target(target_address, target_addressable)
        self.apply_injectables([target])
        self.inject_target(target, dependencies=dep_addresses)
      else:
        for dep_address in dep_addresses:
          if dep_address not in self.dependencies_of(target_address):
            self.inject_dependency(target_address, dep_address)
        target = self.get_target(target_address)

      traversables = [target.compute_dependency_specs(payload=target.payload)]
      # Only poke `traversable_dependency_specs` if a concrete implementation is defined
      # in order to avoid spurious deprecation warnings.
      if type(target).traversable_dependency_specs is not Target.traversable_dependency_specs:
        traversables.append(target.traversable_dependency_specs)

      for traversable_spec in itertools.chain(*traversables):
        traversable_address = Address.parse(traversable_spec, relative_to=target_address.spec_path)
        self.maybe_inject_address_closure(traversable_address)

        if not any(traversable_address == t.address for t in target.dependencies):
          self.inject_dependency(dependent=target.address, dependency=traversable_address)
          target.mark_transitive_invalidation_hash_dirty()

      traversables = [target.compute_injectable_specs(payload=target.payload)]
      # Only poke `traversable_specs` if a concrete implementation is defined
      # in order to avoid spurious deprecation warnings.
      if type(target).traversable_specs is not Target.traversable_specs:
        traversables.append(target.traversable_specs)

      for traversable_spec in itertools.chain(*traversables):
        traversable_address = Address.parse(traversable_spec, relative_to=target_address.spec_path)
        self.maybe_inject_address_closure(traversable_address)
        target.mark_transitive_invalidation_hash_dirty()

    except AddressLookupError as e:
      raise self.TransitiveLookupError("{message}\n  referenced from {spec}"
                                       .format(message=e, spec=target_address.spec))

  def inject_specs_closure(self, specs, fail_fast=None):
    for address in self._address_mapper.scan_specs(specs,
                                                   fail_fast=fail_fast):
      self.inject_address_closure(address)
      yield address

  def _target_addressable_to_target(self, address, addressable):
    """Realizes a TargetAddressable into a Target at `address`.

    :param TargetAddressable addressable:
    :param Address address:
    """
    try:
      # TODO(John Sirois): Today - in practice, Addressable is unusable.  BuildGraph assumes
      # addressables are in fact TargetAddressables with dependencies (see:
      # `inject_address_closure` for example), ie: leaf nameable things with - by definition - no
      # deps cannot actually be used.  Clean up BuildGraph to handle addressables as they are
      # abstracted today which does not necessarily mean them having dependencies and thus forming
      # graphs.  They may only be multiply-referred to leaf objects.
      target = addressable.instantiate(build_graph=self, address=address)
      return target
    except Exception:
      traceback.print_exc()
      logger.exception('Failed to instantiate Target with type {target_type} with name "{name}"'
                       ' at address {address}'
                       .format(target_type=addressable.addressed_type,
                               name=addressable.addressed_name,
                               address=address))
      raise

  def resolve_address(self, address):
    if self.contains_address(address):
      return self.get_target(address)
    else:
      _, addressable = self._address_mapper.resolve(address)
      return addressable
