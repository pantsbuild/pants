# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
from collections import defaultdict

from pants.base.specs import DescendantAddresses
from pants.build_graph.address import Address
from pants.engine.legacy.graph import HydratedTargets, target_types_from_symbol_table
from pants.engine.legacy.source_mapper import EngineSourceMapper
from pants.scm.change_calculator import ChangeCalculator


logger = logging.getLogger(__name__)


class _HydratedTargetDependentGraph(object):
  """A graph for walking dependent addresses of HydratedTarget objects.

  This avoids/imitates constructing a v1 BuildGraph object, because that codepath results
  in many references held in mutable global state (ie, memory leaks).

  The long term goal is to deprecate the `changed` goal in favor of sufficiently good cache
  hit rates, such that rather than running:

    ./pants --changed-parent=master test

  ...you would always be able to run:

    ./pants test ::

  ...and have it complete in a similar amount of time by hitting relevant caches.
  """

  @classmethod
  def from_iterable(cls, target_types, iterable):
    """Create a new HydratedTargetDependentGraph from an iterable of HydratedTarget instances."""
    inst = cls(target_types)
    for hydrated_target in iterable:
      inst.inject_target(hydrated_target)
    return inst

  def __init__(self, target_types):
    self._dependent_address_map = defaultdict(set)
    self._target_types = target_types

  def inject_target(self, hydrated_target):
    """Inject a target, respecting all sources of dependencies."""
    target_cls = self._target_types[hydrated_target.adaptor.type_alias]

    declared_deps = hydrated_target.dependencies
    implicit_deps = (Address.parse(s) for s in target_cls.compute_dependency_specs(kwargs=hydrated_target.adaptor.kwargs()))

    for dep in itertools.chain(declared_deps, implicit_deps):
      self._dependent_address_map[dep].add(hydrated_target.adaptor.address)

  def dependents_of_addresses(self, addresses):
    """Given an iterable of addresses, yield all of those addresses dependents."""
    seen = set(addresses)
    for address in addresses:
      for dependent_address in self._dependent_address_map[address]:
        if dependent_address not in seen:
          seen.add(dependent_address)
          yield dependent_address

  def transitive_dependents_of_addresses(self, addresses):
    """Given an iterable of addresses, yield all of those addresses dependents, transitively."""
    addresses_to_visit = set(addresses)
    while 1:
      dependents = set(self.dependents_of_addresses(addresses))
      # If we've exhausted all dependencies or visited all remaining nodes, break.
      if (not dependents) or dependents.issubset(addresses_to_visit):
        break
      addresses = dependents.difference(addresses_to_visit)
      addresses_to_visit.update(dependents)

    transitive_set = itertools.chain(
      *(self._dependent_address_map[address] for address in addresses_to_visit)
    )
    for dep in transitive_set:
      yield dep


class EngineChangeCalculator(ChangeCalculator):
  """A ChangeCalculator variant that uses the v2 engine for source mapping."""

  def __init__(self, scheduler, symbol_table, scm):
    """
    :param Engine engine: The `Engine` instance to use for computing file to target mappings.
    :param Scm engine: The `Scm` instance to use for computing changes.
    """
    super(EngineChangeCalculator, self).__init__(scm)
    self._scheduler = scheduler
    self._symbol_table = symbol_table
    self._mapper = EngineSourceMapper(self._scheduler)

  def iter_changed_target_addresses(self, changed_request):
    """Given a `ChangedRequest`, compute and yield all affected target addresses."""
    changed_files = self.changed_files(changed_request.changes_since, changed_request.diffspec)
    logger.debug('changed files: %s', changed_files)
    if not changed_files:
      return

    changed_addresses = set(address
                            for address
                            in self._mapper.iter_target_addresses_for_sources(changed_files))
    for address in changed_addresses:
      yield address

    if changed_request.include_dependees not in ('direct', 'transitive'):
      return

    # For dependee finding, we need to parse all build files.
    product_iter = (t
                    for targets in self._scheduler.product_request(HydratedTargets, [DescendantAddresses('')])
                    for t in targets.dependencies)
    graph = _HydratedTargetDependentGraph.from_iterable(target_types_from_symbol_table(self._symbol_table),
                                                        product_iter)

    if changed_request.include_dependees == 'direct':
      for address in graph.dependents_of_addresses(changed_addresses):
        yield address
    elif changed_request.include_dependees == 'transitive':
      for address in graph.transitive_dependents_of_addresses(changed_addresses):
        yield address

  def changed_target_addresses(self, changed_request):
    return list(self.iter_changed_target_addresses(changed_request))
