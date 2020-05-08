# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading

from pants.pantsd.service.pants_service import PantsService
from pants.testutil.test_base import TestBase


class RunnableTestService(PantsService):
    def run(self):
        pass


class TestPantsService(TestBase):
    def setUp(self):
        super().setUp()
        self.service = RunnableTestService()

    def test_init(self):
        self.assertTrue(self.service.name)

    def test_run_abstract(self):
        with self.assertRaises(TypeError):
            PantsService()

    def test_terminate(self):
        self.service.terminate()
        assert self.service._state.is_terminating

    def test_maybe_pause(self):
        # Confirm that maybe_pause with/without a timeout does not deadlock when we are not
        # marked Pausing/Paused.
        self.service._state.maybe_pause(timeout=None)
        self.service._state.maybe_pause(timeout=0.5)

    def test_pause_and_resume(self):
        self.service.mark_pausing()
        # Confirm that we don't transition to Paused without a service thread to maybe_pause.
        self.assertFalse(self.service._state.await_paused(timeout=0.5))
        # Spawn a thread to call maybe_pause.
        t = threading.Thread(target=self.service._state.maybe_pause)
        t.daemon = True
        t.start()
        # Confirm that we observe the pause from the main thread, and that the child thread pauses
        # there without exiting.
        self.assertTrue(self.service._state.await_paused(timeout=5))
        t.join(timeout=0.5)
        self.assertTrue(t.is_alive())
        # Resume the service, and confirm that the child thread exits.
        self.service.resume()
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
