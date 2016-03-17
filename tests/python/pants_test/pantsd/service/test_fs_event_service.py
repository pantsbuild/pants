# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple
from contextlib import contextmanager

import mock

from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.watchman import Watchman
from pants_test.base_test import BaseTest


class TestExecutor(object):
  FakeFuture = namedtuple('FakeFuture', ['done', 'result'])

  def submit(self, closure, *args, **kwargs):
    result = closure(*args, **kwargs)
    return self.FakeFuture(lambda: True, lambda: result)

  def shutdown(self):
    pass


class TestFSEventService(BaseTest):
  BUILD_ROOT = '/build_root'
  EMPTY_EVENT = (None, None)
  FAKE_EVENT = ('test', dict(subscription='test', files=['a/BUILD', 'b/BUILD']))
  FAKE_EVENT_STREAM = [FAKE_EVENT, EMPTY_EVENT, EMPTY_EVENT, FAKE_EVENT, EMPTY_EVENT]
  WORKER_COUNT = 1

  def setUp(self):
    BaseTest.setUp(self)
    self.mock_watchman = mock.create_autospec(Watchman, spec_set=True)
    self.service = FSEventService(self.mock_watchman, self.BUILD_ROOT, self.WORKER_COUNT)
    self.service.setup(TestExecutor())
    self.service.register_all_files_handler(lambda x: True, name='test')
    self.service.register_all_files_handler(lambda x: False, name='test2')

  def test_registration(self):
    # N.B. This test implicitly tests register_handler; no need to duplicate work.
    self.assertTrue('test' in self.service._handlers)
    self.assertTrue('test2' in self.service._handlers)
    self.assertIsInstance(self.service._handlers['test'], Watchman.EventHandler)
    self.assertIsInstance(self.service._handlers['test2'], Watchman.EventHandler)

  def test_register_handler_duplicate(self):
    with self.assertRaises(AssertionError):
      self.service.register_handler('test', 'test', lambda x: True)

    with self.assertRaises(AssertionError):
      self.service.register_handler('test', dict(test=1), lambda x: True)

  def test_fire_callback(self):
    self.assertTrue(self.service.fire_callback('test', {}))
    self.assertFalse(self.service.fire_callback('test2', {}))

  @contextmanager
  def mocked_run(self, asserts=True):
    self.service.fire_callback = mock.Mock()
    yield self.service.fire_callback
    if asserts:
      self.mock_watchman.watch_project.assert_called_once_with(self.BUILD_ROOT)

  def test_run_raise_on_failure_isalive(self):
    self.mock_watchman.is_alive.return_value = False
    with self.mocked_run(False), self.assertRaises(self.service.ServiceError):
      self.service.run()

  def test_run(self):
    with self.mocked_run() as mock_callback:
      self.mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
      self.service.run()
      mock_callback.assert_has_calls([mock.call(*self.FAKE_EVENT), mock.call(*self.FAKE_EVENT)],
                                     any_order=True)

  def test_run_failed_callback(self):
    with self.mocked_run() as mock_callback:
      self.mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
      mock_callback.side_effect = [False, True]
      self.service.run()
      mock_callback.assert_has_calls([mock.call(*self.FAKE_EVENT), mock.call(*self.FAKE_EVENT)],
                                     any_order=True)

  def test_run_breaks_on_kill_switch(self):
    with self.mocked_run() as mock_callback:
      self.service.terminate()
      self.mock_watchman.subscribed.return_value = self.FAKE_EVENT_STREAM
      self.service.run()
      assert not mock_callback.called
