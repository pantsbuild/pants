# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading
import time

from pants.pantsd.service.store_gc_service import StoreGCService
from pants.testutil.test_base import TestBase


class StoreGCServiceTest(TestBase):
    def test_run(self):
        interval_secs = 0.1
        # Start the service in another thread (`setup` is a required part of the service lifecycle, but
        # is unused in this case.)
        sgcs = StoreGCService(
            self.scheduler.scheduler,
            period_secs=(interval_secs / 4),
            lease_extension_interval_secs=interval_secs,
            gc_interval_secs=interval_secs,
        )
        sgcs.setup(services=None)
        t = threading.Thread(target=sgcs.run, name="sgcs")
        t.daemon = True
        t.start()

        # Ensure that the thread runs successfully for long enough to have run each step at least once.
        # TODO: This is a coverage test: although it could examine the internal details of the service
        # to validate correctness, we don't do that yet.
        time.sleep(interval_secs * 10)
        assert t.is_alive()

        # Exit the thread, and then join it.
        sgcs.terminate()
        t.join(timeout=interval_secs * 10)
        assert not t.is_alive()
