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

  _LEASE_EXTENSION_INTERVAL_SECONDS = 30 * 60
  _GARBAGE_COLLECTION_INTERVAL_SECONDS = 4 * 60 * 60

  def __init__(self, scheduler):
    super(StoreGCService, self).__init__()
    self._scheduler = scheduler
    self._logger = logging.getLogger(__name__)

  @staticmethod
  def _launch_thread(f):
    t = threading.Thread(target=f)
    t.daemon = True
    t.start()
    return t

  def _extend_lease(self):
    while 1:
      # Use the fork lock to ensure this thread isn't cloned via fork while holding the graph lock.
      with self.fork_lock:
        self._logger.debug('Extending leases')
        self._scheduler.lease_files_in_graph()
        self._logger.debug('Done extending leases')
      time.sleep(self._LEASE_EXTENSION_INTERVAL_SECONDS)

  def _garbage_collect(self):
    while 1:
      time.sleep(self._GARBAGE_COLLECTION_INTERVAL_SECONDS)
      # Grab the fork lock in case lmdb internally isn't fork-without-exec-safe.
      with self.fork_lock:
        self._logger.debug('Garbage collecting store')
        self._scheduler.garbage_collect_store()
        self._logger.debug('Done garbage collecting store')

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    jobs = (self._extend_lease, self._garbage_collect)
    threads = [self._launch_thread(job) for job in jobs]

    while not self.is_killed:
      for thread in threads:
        # If any job threads die, we want to exit the `PantsService` thread to cause
        # a daemon teardown.
        if not thread.isAlive():
          self._logger.warn('thread {} died - aborting!'.format(thread))
          return
        thread.join(.1)
