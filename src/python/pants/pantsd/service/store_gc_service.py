# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import time

from pants.engine.internals.scheduler import Scheduler
from pants.option.global_options import (
    DEFAULT_LOCAL_STORE_OPTIONS,
    LOCAL_STORE_LEASE_TIME_SECS,
    LocalStoreOptions,
)
from pants.pantsd.service.pants_service import PantsService


class StoreGCService(PantsService):
    """Store Garbage Collection Service.

    This service both ensures that in-use files continue to be present in the engine's Store, and
    performs occasional garbage collection to bound the size of the engine's Store.

    NB: The lease extension interval should be a small multiple of LOCAL_STORE_LEASE_TIME_SECS
    to ensure that valid leases are extended well before they might expire.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        period_secs: float = 10,
        lease_extension_interval_secs: float = (float(LOCAL_STORE_LEASE_TIME_SECS) / 100),
        gc_interval_secs: float = (1 * 60 * 60),
        local_store_options: LocalStoreOptions = DEFAULT_LOCAL_STORE_OPTIONS,
    ):
        super().__init__()
        self._scheduler_session = scheduler.new_session(build_id="store_gc_service_session")
        self._logger = logging.getLogger(__name__)

        self._period_secs = period_secs
        self._lease_extension_interval_secs = lease_extension_interval_secs
        self._gc_interval_secs = gc_interval_secs
        self._target_size_bytes = local_store_options.target_total_size_bytes()

        self._set_next_gc()
        self._set_next_lease_extension()

    def _set_next_gc(self):
        self._next_gc = time.time() + self._gc_interval_secs

    def _set_next_lease_extension(self):
        self._next_lease_extension = time.time() + self._lease_extension_interval_secs

    def _maybe_extend_lease(self):
        if time.time() < self._next_lease_extension:
            return
        self._logger.info("Extending leases")
        self._scheduler_session.lease_files_in_graph()
        self._logger.info("Done extending leases")
        self._set_next_lease_extension()

    def _maybe_garbage_collect(self):
        if time.time() < self._next_gc:
            return
        self._logger.info(f"Garbage collecting store. target_size={self._target_size_bytes:,}")
        self._scheduler_session.garbage_collect_store(self._target_size_bytes)
        self._logger.info("Done garbage collecting store")
        self._set_next_gc()

    def run(self):
        """Main service entrypoint.

        Called via Thread.start() via PantsDaemon.run().
        """
        while not self._state.is_terminating:
            try:
                self._maybe_garbage_collect()
                self._maybe_extend_lease()
                # Waiting with a timeout in maybe_pause has the effect of waiting until:
                # 1) we are paused and then resumed
                # 2) we are terminated (which will break the loop)
                # 3) the timeout is reached, which will cause us to wake up and check gc/leases
                self._state.maybe_pause(timeout=self._period_secs)
            except Exception as e:
                self._logger.critical(f"GC failed: {e!r}")
                self.terminate()
        self._scheduler_session.cancel()
