# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

import mock

from pants.pantsd.pants_daemon import PantsDaemon, _StreamLogger
from pants.pantsd.service.pants_service import PantsService
from pants.util.contextutil import stdio_as
from pants_test.base_test import BaseTest


PATCH_OPTS = dict(autospec=True, spec_set=True)


class StreamLoggerTest(BaseTest):

  TEST_LOG_LEVEL = logging.INFO

  def test_write(self):
    mock_logger = mock.Mock()
    _StreamLogger(mock_logger, self.TEST_LOG_LEVEL).write('testing 1 2 3')
    mock_logger.log.assert_called_once_with(self.TEST_LOG_LEVEL, 'testing 1 2 3')

  def test_write_multiline(self):
    mock_logger = mock.Mock()
    _StreamLogger(mock_logger, self.TEST_LOG_LEVEL).write('testing\n1\n2\n3\n\n')
    mock_logger.log.assert_has_calls([
      mock.call(self.TEST_LOG_LEVEL, 'testing'),
      mock.call(self.TEST_LOG_LEVEL, '1'),
      mock.call(self.TEST_LOG_LEVEL, '2'),
      mock.call(self.TEST_LOG_LEVEL, '3')
    ])

  def test_flush(self):
    _StreamLogger(mock.Mock(), self.TEST_LOG_LEVEL).flush()


class PantsDaemonTest(BaseTest):
  def setUp(self):
    super(PantsDaemonTest, self).setUp()
    self.pantsd = PantsDaemon('test_buildroot',
                              'test_work_dir',
                              logging.INFO,
                              None,
                              log_dir='/non_existent',
                              metadata_base_dir=self.subprocess_dir)
    self.pantsd.set_services([])
    self.pantsd.set_socket_map({})

    self.mock_killswitch = mock.Mock()
    self.pantsd._kill_switch = self.mock_killswitch

    self.mock_service = mock.create_autospec(PantsService, spec_set=True)

  @mock.patch('os.close', **PATCH_OPTS)
  def test_close_fds(self, mock_close):
    mock_fd = mock.Mock()
    mock_fd.fileno.side_effect = [0, 1, 2]

    with stdio_as(mock_fd, mock_fd, mock_fd):
      self.pantsd._close_fds()

    self.assertEquals(mock_fd.close.call_count, 3)
    mock_close.assert_has_calls(mock.call(x) for x in [0, 1, 2])

  def test_shutdown(self):
    mock_thread = mock.Mock()
    mock_service_thread_map = {self.mock_service: mock_thread}

    self.pantsd.shutdown(mock_service_thread_map)

    self.mock_service.terminate.assert_called_once_with()
    self.assertTrue(self.pantsd.is_killed)
    mock_thread.join.assert_called_once_with()

  def test_run_services_no_services(self):
    self.pantsd._run_services([])

  @mock.patch('threading.Thread', **PATCH_OPTS)
  @mock.patch.object(PantsDaemon, 'shutdown', spec_set=True)
  def test_run_services_startupfailure(self, mock_shutdown, mock_thread):
    mock_thread.return_value.start.side_effect = RuntimeError('oops!')

    with self.assertRaises(PantsDaemon.StartupFailure):
      self.pantsd._run_services([self.mock_service])

    self.assertGreater(mock_shutdown.call_count, 0)

  @mock.patch('threading.Thread', **PATCH_OPTS)
  @mock.patch.object(PantsDaemon, 'shutdown', spec_set=True)
  def test_run_services_runtimefailure(self, mock_shutdown, mock_thread):
    self.mock_killswitch.is_set.side_effect = [False, False, True]
    mock_thread.return_value.is_alive.side_effect = [True, False]

    with self.assertRaises(PantsDaemon.RuntimeFailure):
      self.pantsd._run_services([self.mock_service])

    self.assertGreater(mock_shutdown.call_count, 0)
