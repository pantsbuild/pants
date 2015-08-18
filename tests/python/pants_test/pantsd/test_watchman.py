# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import sys
from contextlib import contextmanager

import mock
import pywatchman

from pants.pantsd.watchman import Watchman
from pants.pantsd.watchman_client import StreamableWatchmanClient
from pants.util.contextutil import environment_as
from pants_test.base_test import BaseTest


class TestWatchman(BaseTest):
  PATCH_OPTS = dict(autospec=True, spec_set=True)
  WORK_DIR = '/path/to/a/fake/work_dir'
  BUILD_ROOT = '/path/to/a/fake/build_root'
  WATCHMAN_PATH = '/path/to/a/fake/watchman'
  TEST_DIR = '/path/to/a/fake/test'
  WATCHMAN_DIR = os.path.join(WORK_DIR, 'watchman')
  STATE_FILE = os.path.join(WATCHMAN_DIR, 'watchman.state')
  HANDLERS = [Watchman.EventHandler('test', {}, mock.Mock())]

  def setUp(self):
    BaseTest.setUp(self)
    with mock.patch.object(Watchman, '_resolve_watchman_path', **self.PATCH_OPTS) as mock_find:
      mock_find.return_value = self.WATCHMAN_PATH
      self.watchman = Watchman(self.WORK_DIR)

  def test_client_property(self):
    self.assertIsInstance(self.watchman.client, pywatchman.client)

  def test_client_property_cached(self):
    self.watchman._watchman_client = 1
    self.assertEquals(self.watchman.client, 1)

  def test_make_client(self):
    self.assertIsInstance(self.watchman._make_client(), pywatchman.client)

  def test_is_valid_executable(self):
    self.assertTrue(self.watchman._is_valid_executable(sys.executable))

  @contextmanager
  def setup_find_watchman_in_path(self):
    with mock.patch.object(Watchman, '_is_valid_executable', **self.PATCH_OPTS) as mock_valid, \
         environment_as(PATH='a:b:c'):
      yield mock_valid

  def test_find_watchman_in_path(self):
    with self.setup_find_watchman_in_path() as mock_valid:
      mock_valid.side_effect = [False, False, True]
      self.assertEquals(self.watchman._find_watchman_in_path(), 'c/watchman')
      mock_valid.assert_has_calls([
        mock.call(self.watchman, 'a/{}'.format(self.watchman.process_name)),
        mock.call(self.watchman, 'b/{}'.format(self.watchman.process_name)),
        mock.call(self.watchman, 'c/{}'.format(self.watchman.process_name))
      ])

  def test_find_watchman_in_path_neg(self):
    with self.setup_find_watchman_in_path() as mock_valid:
      mock_valid.side_effect = [False, False, False]
      self.assertIsNone(self.watchman._find_watchman_in_path())

  def test_resolve_watchman_path_provided_exception(self):
    with mock.patch.object(Watchman, '_is_valid_executable', **self.PATCH_OPTS) as mock_valid:
      mock_valid.return_value = False
      with self.assertRaises(Watchman.ExecutionError):
        self.watchman._resolve_watchman_path(self.WATCHMAN_PATH)

  def test_resolve_watchman_path_provided(self):
    with mock.patch.object(Watchman, '_is_valid_executable', **self.PATCH_OPTS) as mock_valid:
      mock_valid.return_value = True
      self.assertEquals(self.watchman._resolve_watchman_path(self.WATCHMAN_PATH),
                        self.WATCHMAN_PATH)

  def test_resolve_watchman_path_default_exception(self):
    with mock.patch.object(Watchman, '_find_watchman_in_path', **self.PATCH_OPTS) as mock_find:
      mock_find.return_value = None
      with self.assertRaises(Watchman.ExecutionError):
        self.watchman._resolve_watchman_path(None)

  def test_resolve_watchman_path_default(self):
    with mock.patch.object(Watchman, '_find_watchman_in_path', **self.PATCH_OPTS) as mock_find:
      mock_find.return_value = self.WATCHMAN_PATH
      self.assertEquals(self.watchman._resolve_watchman_path(None), self.WATCHMAN_PATH)

  def test_maybe_init_metadata(self):
    with mock.patch('pants.pantsd.watchman.safe_mkdir', **self.PATCH_OPTS) as mock_mkdir, \
         mock.patch.object(Watchman, '_write_file', **self.PATCH_OPTS) as mock_write_file:
      self.watchman._maybe_init_metadata()

      mock_mkdir.assert_called_once_with(self.WATCHMAN_DIR)
      mock_write_file.assert_called_once_with(self.watchman, self.STATE_FILE, '{}')

  def test_construct_cmd(self):
    output = self.watchman._construct_cmd(['cmd', 'parts', 'etc'],
                                          'state_file',
                                          'sock_file',
                                          'log_file',
                                          'log_level')

    self.assertEquals(output, ['cmd',
                               'parts',
                               'etc',
                               '--no-save-state',
                               '--statefile=state_file',
                               '--sockname=sock_file',
                               '--logfile=log_file',
                               '--log-level',
                               'log_level'])

  def test_parse_pid_from_output(self):
    output = json.dumps(dict(pid=3))
    self.assertEquals(self.watchman._parse_pid_from_output(output), 3)

  def test_parse_pid_from_output_bad_output(self):
    output = '{bad JSON.,/#!'
    with self.assertRaises(self.watchman.InvalidCommandOutput):
      self.watchman._parse_pid_from_output(output)

  def test_parse_pid_from_output_no_pid(self):
    output = json.dumps(dict(nothing=True))
    with self.assertRaises(self.watchman.InvalidCommandOutput):
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
      self.assertEquals(list(out), [(None, None)])

  def test_subscribed_response(self):
    """Test yielding on the watchman response to the initial subscribe command."""
    with self.setup_subscribed([dict(subscribe='test')]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEquals(list(out), [(None, None)])

  def test_subscribed_event(self):
    """Test yielding on a watchman event for a given subscription."""
    test_event = dict(subscription='test3', msg='blah')

    with self.setup_subscribed([test_event]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEquals(list(out), [('test3', test_event)])

  def test_subscribed_unknown_event(self):
    """Test yielding on an unknown watchman event."""
    with self.setup_subscribed([dict(unknown=True)]):
      out = self.watchman.subscribed(self.BUILD_ROOT, self.HANDLERS)
      self.assertEquals(list(out), [])
