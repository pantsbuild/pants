# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading
from contextlib import contextmanager

import mock

from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.watchman import Watchman
from pants_test.base_test import BaseTest


class TestFSEventService(BaseTest):
  PATCH_OPTS = dict(autospec=True, spec_set=True)
  BUILD_ROOT = '/build_root'
  EMPTY_EVENT = (None, None)
  FAKE_EVENT = ('test', dict(subscription='test', files=['a/BUILD', 'b/BUILD']))
  FAKE_EVENT_STREAM = [FAKE_EVENT, EMPTY_EVENT, EMPTY_EVENT, FAKE_EVENT, EMPTY_EVENT]

  @classmethod
  def setUpClass(cls):
    FSEventService.register_simple_handler('test', lambda x: True)
    FSEventService.register_simple_handler('test2', lambda x: False)

  def setUp(self):
    BaseTest.setUp(self)
    self.event = threading.Event()
    self.service = FSEventService(self.BUILD_ROOT, 8, self.event)

  def test_register_simple_handler(self):
    # N.B. This test implicitly tests register_handler; no need to duplicate work.
    self.assertTrue('test' in FSEventService.HANDLERS)
    self.assertTrue('test2' in FSEventService.HANDLERS)
    self.assertIsInstance(FSEventService.HANDLERS['test'], Watchman.EventHandler)
    self.assertIsInstance(FSEventService.HANDLERS['test2'], Watchman.EventHandler)

  def test_register_simple_handler_duplicate(self):
    with self.assertRaises(AssertionError):
      FSEventService.register_simple_handler('test', lambda x: True)

  def test_register_handler_duplicate(self):
    with self.assertRaises(AssertionError):
      FSEventService.register_handler('test', 'test', lambda x: True)

    with self.assertRaises(AssertionError):
      FSEventService.register_handler('test', dict(test=1), lambda x: True)

  def test_fire_callback(self):
    self.assertTrue(FSEventService.fire_callback('test', {}))
    self.assertFalse(FSEventService.fire_callback('test2', {}))

  @contextmanager
  def mocked_run(self, asserts=True):
    with mock.patch('pants.pantsd.service.fs_event_service.WatchmanLauncher',
                    **self.PATCH_OPTS) as mock_watchman_launcher, \
         mock.patch('pants.pantsd.service.fs_event_service.Watchman',
                    **self.PATCH_OPTS) as mock_watchman:
      mock_watchman_launcher.global_instance.return_value = mock_watchman_launcher
      mock_watchman_launcher.maybe_launch.return_value = mock_watchman
      self.service.fire_callback = mock.Mock()
      yield mock_watchman, mock_watchman_launcher, self.service.fire_callback
      if asserts:
        mock_watchman.watch_project.assert_called_once_with(self.BUILD_ROOT)

  def test_run_raise_on_failure_isalive(self):
    with self.mocked_run(False) as (mock_watchman, mock_watchman_launcher, mock_callback):
      with self.assertRaises(FSEventService.ServiceError):
        mock_watchman.is_alive.return_value = False
        self.service.run()

  def test_run_raise_on_failure_launch(self):
    with self.mocked_run(False) as (mock_watchman, mock_watchman_launcher, mock_callback):
      with self.assertRaises(FSEventService.ServiceError):
        mock_watchman_launcher.maybe_launch.return_value = False
        self.service.run()

  def test_run(self):
    with self.mocked_run() as (mock_watchman, mock_watchman_launcher, mock_callback):
      mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
      self.service.run()
      mock_callback.assert_has_calls([mock.call(*self.FAKE_EVENT), mock.call(*self.FAKE_EVENT)],
                                     any_order=True)

  def test_run_failed_callback(self):
    with self.mocked_run() as (mock_watchman, mock_watchman_launcher, mock_callback):
      mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
      mock_callback.side_effect = [False, True]
      self.service.run()
      mock_callback.assert_has_calls([mock.call(*self.FAKE_EVENT), mock.call(*self.FAKE_EVENT)],
                                     any_order=True)

  def test_run_breaks_on_kill_switch(self):
    with self.mocked_run() as (mock_watchman, mock_watchman_launcher, mock_callback):
      self.service._kill_switch.set()
      mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
      self.service.run()
      assert not mock_callback.called
