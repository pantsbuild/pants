# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.engine.legacy.source_mapper import EngineSourceMapper
from pants.scm.change_calculator import ChangeCalculator


logger = logging.getLogger(__name__)


class EngineChangeCalculator(ChangeCalculator):
  """A ChangeCalculator variant that uses the v2 engine for source mapping."""

  def __init__(self, engine, scm, fast=False):
    super(EngineChangeCalculator, self).__init__(scm)
    self._engine = engine
    self._mapper_cache = None

  @property
  def _mapper(self):
    if self._mapper_cache is None:
      self._mapper_cache = EngineSourceMapper(self._engine)
    return self._mapper_cache

  def changed_target_addresses(self, changed_request):
    return list(self._changed_target_addresses(changed_request))

  def _changed_target_addresses(self, changed_request):
    changed_files = self.changed_files(changed_request)
    logger.debug('changed files: %s', changed_files)
    for address in self._mapper.iter_target_addresses_for_sources(changed_files):
      yield address
