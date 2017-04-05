# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.specs import DescendantAddresses
from pants.engine.legacy.graph import LegacyBuildGraph
from pants.engine.legacy.source_mapper import EngineSourceMapper
from pants.scm.change_calculator import ChangeCalculator


logger = logging.getLogger(__name__)


class EngineChangeCalculator(ChangeCalculator):
  """A ChangeCalculator variant that uses the v2 engine for source mapping."""

  def __init__(self, scheduler, engine, symbol_table_cls, scm):
    """
    :param Engine engine: The `Engine` instance to use for computing file to target mappings.
    :param Scm engine: The `Scm` instance to use for computing changes.
    """
    super(EngineChangeCalculator, self).__init__(scm)
    self._scheduler = scheduler
    self._engine = engine
    self._symbol_table_cls = symbol_table_cls
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
    graph = LegacyBuildGraph.create(self._scheduler, self._engine, self._symbol_table_cls)
    for _ in graph.inject_specs_closure([DescendantAddresses('')]):
      pass

    if changed_request.include_dependees == 'direct':
      emitted = set()
      for address in changed_addresses:
        for dependee in graph.dependents_of(address):
          if dependee not in emitted:
            emitted.add(dependee)
            yield dependee
    elif changed_request.include_dependees == 'transitive':
      for target in graph.transitive_dependees_of_addresses(changed_addresses):
        yield target.address

  def changed_target_addresses(self, changed_request):
    return list(self.iter_changed_target_addresses(changed_request))
