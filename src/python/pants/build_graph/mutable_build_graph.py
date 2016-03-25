# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import traceback

from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph


logger = logging.getLogger(__name__)


class MutableBuildGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected."""

  def __init__(self, address_mapper):
    self._address_mapper = address_mapper
    super(MutableBuildGraph, self).__init__()

  def reset(self):
    super(MutableBuildGraph, self).reset()
    self._addresses_already_closed = set()
    self._derived_from_by_derivative_address = {}
    self.synthetic_addresses = set()

  def get_derived_from(self, address):
    parent_address = self._derived_from_by_derivative_address.get(address, address)
    return self.get_target(parent_address)

  def get_concrete_derived_from(self, address):
    current_address = address
    next_address = self._derived_from_by_derivative_address.get(current_address, current_address)
    while next_address != current_address:
      current_address = next_address
      next_address = self._derived_from_by_derivative_address.get(current_address, current_address)
    return self.get_target(current_address)

  def inject_target(self, target, dependencies=None, derived_from=None, synthetic=False):
    dependencies = dependencies or frozenset()
    address = target.address

    if address in self._target_by_address:
      raise ValueError('A Target {existing_target} already exists in the BuildGraph at address'
                       ' {address}.  Failed to insert {target}.'
                       .format(existing_target=self._target_by_address[address],
                               address=address,
                               target=target))

    if derived_from:
      if not self.contains_address(derived_from.address):
        raise ValueError('Attempted to inject synthetic {target} derived from {derived_from}'
                         ' into the BuildGraph, but {derived_from} was not in the BuildGraph.'
                         ' Synthetic Targets must be derived from no Target (None) or from a'
                         ' Target already in the BuildGraph.'
                         .format(target=target,
                                 derived_from=derived_from))
      self._derived_from_by_derivative_address[target.address] = derived_from.address

    if derived_from or synthetic:
      self.synthetic_addresses.add(address)

    self._target_by_address[address] = target

    for dependency_address in dependencies:
      self.inject_dependency(dependent=address, dependency=dependency_address)

  def inject_dependency(self, dependent, dependency):
    if dependent not in self._target_by_address:
      raise ValueError('Cannot inject dependency from {dependent} on {dependency} because the'
                       ' dependent is not in the BuildGraph.'
                       .format(dependent=dependent, dependency=dependency))

    # TODO(pl): Unfortunately this is an unhelpful time to error due to a cycle.  Instead, we warn
    # and allow the cycle to appear.  It is the caller's responsibility to call sort_targets on the
    # entire graph to generate a friendlier CycleException that actually prints the cycle.
    # Alternatively, we could call sort_targets after every inject_dependency/inject_target, but
    # that could have nasty performance implications.  Alternative 2 would be to have an internal
    # data structure of the topologically sorted graph which would have acceptable amortized
    # performance for inserting new nodes, and also cycle detection on each insert.

    if dependency not in self._target_by_address:
      logger.warning('Injecting dependency from {dependent} on {dependency}, but the dependency'
                     ' is not in the BuildGraph.  This probably indicates a dependency cycle, but'
                     ' it is not an error until sort_targets is called on a subgraph containing'
                     ' the cycle.'
                     .format(dependent=dependent, dependency=dependency))

    if dependency in self.dependencies_of(dependent):
      logger.debug('{dependent} already depends on {dependency}'
                   .format(dependent=dependent, dependency=dependency))
    else:
      self._target_dependencies_by_address[dependent].add(dependency)
      self._target_dependees_by_address[dependency].add(dependent)

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    if self.contains_address(address):
      raise ValueError('Attempted to inject synthetic {target_type} derived from {derived_from}'
                       ' into the BuildGraph with address {address}, but there is already a Target'
                       ' {existing_target} with that address'
                       .format(target_type=target_type,
                               derived_from=derived_from,
                               address=address,
                               existing_target=self.get_target(address)))

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
        self.inject_target(target, dependencies=dep_addresses)
      else:
        for dep_address in dep_addresses:
          if dep_address not in self.dependencies_of(target_address):
            self.inject_dependency(target_address, dep_address)
        target = self.get_target(target_address)

      def inject_spec_closure(spec):
        # Check to see if the target is synthetic or not.  If we find a synthetic target then
        # short circuit the inject_address_closure since mapper.spec_to_address expects an actual
        # BUILD file to exist on disk.
        maybe_synthetic_address = Address.parse(spec, relative_to=target_address.spec_path)
        if not self.contains_address(maybe_synthetic_address):
          addr = mapper.spec_to_address(spec, relative_to=target_address.spec_path)
          self.inject_address_closure(addr)

      for traversable_spec in target.traversable_dependency_specs:
        inject_spec_closure(traversable_spec)
        traversable_spec_target = self.get_target_from_spec(traversable_spec,
                                                            relative_to=target_address.spec_path)

        if traversable_spec_target not in target.dependencies:
          self.inject_dependency(dependent=target.address,
                                 dependency=traversable_spec_target.address)
          target.mark_transitive_invalidation_hash_dirty()

      for traversable_spec in target.traversable_specs:
        inject_spec_closure(traversable_spec)
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
