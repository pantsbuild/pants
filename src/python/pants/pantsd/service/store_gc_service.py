# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import time

from pants.pantsd.service.pants_service import PantsService


class StoreGCService(PantsService):
  """Store Garbage Collection Service.

  This service both ensures that in-use files continue to be present in the engine's Store, and
  performs occasional garbage collection to bound the size of the engine's Store.
  """

  _LEASE_EXTENSION_INTERVAL_SECONDS = 30 * 60
  _GARBAGE_COLLECTION_INTERVAL_SECONDS = 4 * 60 * 60

  def __init__(self, scheduler):
    super(StoreGCService, self).__init__()
    self._scheduler = scheduler
    self._logger = logging.getLogger(__name__)

    self._set_next_gc()
    self._set_next_lease_extension()

  def _set_next_gc(self):
    self._next_gc = time.time() + self._GARBAGE_COLLECTION_INTERVAL_SECONDS

  def _set_next_lease_extension(self):
    self._next_lease_extension = time.time() + self._LEASE_EXTENSION_INTERVAL_SECONDS

  def _maybe_extend_lease(self):
    if time.time() < self._next_lease_extension:
      return
    self._logger.debug('Extending leases')
    self._scheduler.lease_files_in_graph()
    self._logger.debug('Done extending leases')
    self._set_next_lease_extension()

  def _maybe_garbage_collect(self):
    if time.time() < self._next_gc:
      return
    self._logger.debug('Garbage collecting store')
    self._scheduler.garbage_collect_store()
    self._logger.debug('Done garbage collecting store')
    self._set_next_gc()

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    while not self._state.is_terminating:
      self._maybe_garbage_collect()
      self._maybe_extend_lease()
      # Waiting with a timeout in maybe_pause has the effect of waiting until:
      # 1) we are paused and then resumed
      # 2) we are terminated (which will break the loop)
      # 3) the timeout is reached, which will cause us to wake up and check gc/leases
      self._state.maybe_pause(timeout=10)
