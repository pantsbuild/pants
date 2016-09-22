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
from pants.engine.legacy.graph import LegacyTarget
from pants.engine.legacy.source_mapper import EngineSourceMapper, resolve_and_parse_specs
from pants.scm.change_calculator import ChangeCalculator


logger = logging.getLogger(__name__)


class _LegacyTargetDependentGraph(object):
  """A graph for walking dependent addresses of LegacyTarget objects."""

  @classmethod
  def from_iterable(cls, iterable):
    """Create a new LegacyTargetDependentGraph from an iterable of LegacyTarget instances."""
    inst = cls()
    for legacy_target in iterable:
      inst.inject_target(legacy_target)
    return inst

  def __init__(self):
    self._dependent_address_map = defaultdict(set)

  def _resources_addresses(self, legacy_target):
    """Yields fully qualified string addresses of resources for a given `LegacyTarget`."""
    kwargs = legacy_target.adaptor.kwargs()

    # TODO: Figure out a better way to filter these.
    # Python targets `resources` are lists of files, not addresses - short circuit for them.
    if kwargs.get('type_alias', '').startswith('python_'):
      return

    resource_specs = kwargs.get('resources', [])
    if not resource_specs:
      return

    parsed_resource_specs = resolve_and_parse_specs(legacy_target.adaptor.address.spec_path,
                                                    resource_specs)
    for spec in parsed_resource_specs:
      yield Address.parse(spec.to_spec_string())

  def inject_target(self, legacy_target):
    """Inject a target, respecting both its direct dependencies and its resources targets."""
    for dep in itertools.chain(legacy_target.dependencies, self._resources_addresses(legacy_target)):
      self._dependent_address_map[dep].add(legacy_target.adaptor.address)

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

  def __init__(self, engine, scm):
    """
    :param Engine engine: The `Engine` instance to use for computing file to target mappings.
    :param Scm engine: The `Scm` instance to use for computing changes.
    """
    super(EngineChangeCalculator, self).__init__(scm)
    self._engine = engine
    self._mapper = EngineSourceMapper(engine)

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
    product_iter = self._engine.product_request(LegacyTarget, [DescendantAddresses('')])
    graph = _LegacyTargetDependentGraph.from_iterable(product_iter)

    if changed_request.include_dependees == 'direct':
      for address in graph.dependents_of_addresses(changed_addresses):
        yield address
    elif changed_request.include_dependees == 'transitive':
      for address in graph.transitive_dependents_of_addresses(changed_addresses):
        yield address

  def changed_target_addresses(self, changed_request):
    return list(self.iter_changed_target_addresses(changed_request))
