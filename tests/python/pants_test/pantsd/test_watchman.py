# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import sys
from contextlib import contextmanager

import mock
import pywatchman

from pants.pantsd.watchman import Watchman
from pants.pantsd.watchman_client import StreamableWatchmanClient
from pants_test.test_base import TestBase


class TestWatchman(TestBase):
  PATCH_OPTS = dict(autospec=True, spec_set=True)
  BUILD_ROOT = '/path/to/a/fake/build_root'
  WATCHMAN_PATH = '/path/to/a/fake/watchman'
  TEST_DIR = '/path/to/a/fake/test'
  HANDLERS = [Watchman.EventHandler('test', {}, mock.Mock())]

  def setUp(self):
    super(TestWatchman, self).setUp()
    with mock.patch.object(Watchman, '_is_valid_executable', **self.PATCH_OPTS) as mock_is_valid:
      mock_is_valid.return_value = True
      self.watchman = Watchman('/fake/path/to/watchman', self.subprocess_dir)

  @property
  def _watchman_dir(self):
    return os.path.join(self.subprocess_dir, 'watchman')

  @property
  def _state_file(self):
    return os.path.join(self._watchman_dir, 'watchman.state')

  def test_client_property(self):
    self.assertIsInstance(self.watchman.client, pywatchman.client)

  def test_client_property_cached(self):
    self.watchman._watchman_client = 1
    self.assertEqual(self.watchman.client, 1)

  def test_make_client(self):
    self.assertIsInstance(self.watchman._make_client(), pywatchman.client)

  def test_is_valid_executable(self):
    self.assertTrue(self.watchman._is_valid_executable(sys.executable))

  def test_resolve_watchman_path_provided_exception(self):
    with self.assertRaises(Watchman.ExecutionError):
      self.watchman = Watchman('/fake/path/to/watchman',
                               metadata_base_dir=self.subprocess_dir)

  def test_maybe_init_metadata(self):
    # TODO(#7106): is this the right path to patch?
    with mock.patch('pants.pantsd.watchman.safe_mkdir', **self.PATCH_OPTS) as mock_mkdir, \
         mock.patch('pants.pantsd.watchman.safe_file_dump', **self.PATCH_OPTS) as mock_file_dump:
      self.watchman._maybe_init_metadata()

      mock_mkdir.assert_called_once_with(self._watchman_dir)
      mock_file_dump.assert_called_once_with(self._state_file, b'{}', mode='wb')

  def test_construct_cmd(self):
    output = self.watchman._construct_cmd(['cmd', 'parts', 'etc'],
                                          'state_file',
                                          'sock_file',
                                          'pid_file',
                                          'log_file',
                                          'log_level')

    self.assertEqual(output, ['cmd',
                               'parts',
                               'etc',
                               '--no-save-state',
                               '--no-site-spawner',
                               '--statefile=state_file',
                               '--sockname=sock_file',
                               '--pidfile=pid_file',
                               '--logfile=log_file',
                               '--log-level',
                               'log_level'])

  def test_parse_pid_from_output(self):
    output = json.dumps(dict(pid=3))
    self.assertEqual(self.watchman._parse_pid_from_output(output), 3)

  def test_parse_pid_from_output_bad_output(self):
    output = '{bad JSON.,/#!'
    with self.assertRaises(Watchman.InvalidCommandOutput):
      self.watchman._parse_pid_from_output(output)

  def test_parse_pid_from_output_no_pid(self):
    output = json.dumps(dict(nothing=True))
    with self.assertRaises(Watchman.InvalidCommandOutput):
      self.watchman._parse_pid_from_output(output)

  def test_launch(self):
    with mock.patch.object(Watchman, '_maybe_init_metadata') as mock_initmeta, \
         mock.patch.object(Watchman, 'get_subprocess_output') as mock_getsubout, \
         mock.patch.object(Watchman, 'write_pid') as mock_writepid, \
         mock.patch.object(Watchman, 'write_socket') as mock_writesock:
      mock_getsubout.return_value = json.dumps(dict(pid='3'))
      self.watchman.launch()
      assert mock_getsubout.called
      mock_initmeta.assert_called_once_with()
      mock_writepid.assert_called_once_with('3')
      mock_writesock.assert_called_once_with(self.watchman._sock_file)

  def test_watch_project(self):
    self.watchman._watchman_client = mock.create_autospec(StreamableWatchmanClient, spec_set=True)
    self.watchman.watch_project(self.TEST_DIR)
    self.watchman._watchman_client.query.assert_called_once_with('watch-project', self.TEST_DIR)

  @contextmanager
  def setup_subscribed(self, iterable):
    mock_client = mock.create_autospec(StreamableWatchmanClient, spec_set=True)
    mock_client.stream_query.return_value = iter(iterable)
    self.watchman._watchman_client = mock_client
    yield mock_client
    assert mock_client.stream_query.called

  def test_subscribed_empty(self):
    """Test yielding when watchman reads timeout."""
    with self.setup_subscribed([None]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEqual(list(out), [(None, None)])

  def test_subscribed_response(self):
    """Test yielding on the watchman response to the initial subscribe command."""
    with self.setup_subscribed([dict(subscribe='test')]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEqual(list(out), [(None, None)])

  def test_subscribed_event(self):
    """Test yielding on a watchman event for a given subscription."""
    test_event = dict(subscription='test3', msg='blah')

    with self.setup_subscribed([test_event]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEqual(list(out), [('test3', test_event)])

  def test_subscribed_unknown_event(self):
    """Test yielding on an unknown watchman event."""
    with self.setup_subscribed([dict(unknown=True)]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEqual(list(out), [])
