# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import threading
import time

from pants.pantsd.service.pants_service import PantsService

class StoreGCService(PantsService):
  """Store Garbage Collection Service.

  This service both ensures that in-use files continue to be present in the engine's Store, and
  performs occasional garbage collection to bound the size of the engine's Store.
  """

  def __init__(self, scheduler):
    super(StoreGCService, self).__init__()
    self._scheduler = scheduler
    self._logger = logging.getLogger(__name__)
    self._lease_extension_thread = None
    self._garbage_collection_thread = None

  def setup(self, lifecycle_lock, fork_lock):
    super(StoreGCService, self).setup(lifecycle_lock, fork_lock)

  def _extend_lease(self):
    while True:
      self._logger.debug("Extending leases")
      self._scheduler.lease_files_in_graph()
      self._logger.debug("Done extending leases")
      time.sleep(30 * 60)

  def _garbage_collect(self):
    while True:
      time.sleep(4 * 60 * 60)
      # Grab the fork lock to ensure this thread isn't cloned by a fork while holding the graph
      # lock.
      self.fork_lock.acquire()
      try:
        self._logger.debug("Garbage collecting store")
        self._scheduler.garbage_collect_store()
      finally:
        self.fork_lock.release()
        self._logger.debug("Done garbage collecting store")

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    self._lease_extension_thread = threading.Thread(target=self._extend_lease)
    self._lease_extension_thread.daemon = False
    self._lease_extension_thread.start()

    self._garbage_collection_thread = threading.Thread(target=self._garbage_collect)
    self._garbage_collection_thread.daemon = False
    self._garbage_collection_thread.start()

    while not self.is_killed:
      time.sleep(1)
