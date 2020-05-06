# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest.mock
from contextlib import contextmanager

from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.watchman import Watchman
from pants.testutil.test_base import TestBase


class TestFSEventService(TestBase):
    BUILD_ROOT = "/build_root"
    EMPTY_EVENT = (None, None)
    FAKE_EVENT = dict(subscription="test", files=["a/BUILD", "b/BUILD"])
    FAKE_EVENT_STREAM = [
        ("ignored", ev) for ev in [FAKE_EVENT, EMPTY_EVENT, EMPTY_EVENT, FAKE_EVENT, EMPTY_EVENT]
    ]
    WORKER_COUNT = 1

    def setUp(self):
        super().setUp()
        self.mock_watchman = unittest.mock.create_autospec(Watchman, spec_set=True)
        self.service = FSEventService(self.mock_watchman, self.scheduler.scheduler, self.BUILD_ROOT)
        self.service.setup(None)

    @contextmanager
    def mocked_run(self, asserts=True):
        self.service._handle_all_files_event = unittest.mock.Mock()
        yield self.service._handle_all_files_event
        if asserts:
            self.mock_watchman.watch_project.assert_called_once_with(self.BUILD_ROOT)

    def test_run_raise_on_failure_isalive(self):
        self.mock_watchman.is_alive.return_value = False
        with self.mocked_run(False), self.assertRaises(FSEventService.ServiceError):
            self.service.run()

    def test_run(self):
        with self.mocked_run() as mock_callback:
            self.mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
            self.service.run()
            mock_callback.assert_has_calls(
                [unittest.mock.call(self.FAKE_EVENT), unittest.mock.call(self.FAKE_EVENT)],
                any_order=True,
            )

    def test_run_breaks_on_kill_switch(self):
        with self.mocked_run() as mock_callback:
            self.service.terminate()
            self.mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
            self.service.run()
            assert not mock_callback.called
