# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import re
from builtins import open, str

import mock

from pants.base.exception_sink import ExceptionSink
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants_test.test_base import TestBase


class TestExceptionSink(TestBase):

  def _gen_sink_subclass(self):
    # Avoid modifying global state by generating a subclass.
    class AnonymousSink(ExceptionSink): pass
    return AnonymousSink

  def test_unset_destination(self):
    self.assertEqual(os.getcwd(), self._gen_sink_subclass()._log_dir)

  def test_retrieve_destination(self):
    sink = self._gen_sink_subclass()

    with temporary_dir() as tmpdir:
      sink.reset_log_location(tmpdir, os.getpid())
      self.assertEqual(tmpdir, sink._log_dir)

  def test_set_invalid_destination(self):
    sink = self._gen_sink_subclass()
    err_rx = re.escape(
      "The provided exception sink path at '/does/not/exist' is not writable or could not be created: [Errno 13]")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.reset_log_location('/does/not/exist', os.getpid())
    err_rx = '{}.*{}'.format(
      re.escape("Error opening fatal error log streams in / for pid "),
      re.escape(": [Errno 13] Permission denied: '/logs'"))
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.reset_log_location('/', os.getpid())

  def test_log_exception(self):
    sink = self._gen_sink_subclass()
    pid = os.getpid()
    with temporary_dir() as tmpdir:
      # Check that tmpdir exists, and log an exception into that directory.
      sink.reset_log_location(tmpdir, os.getpid())
      sink.log_exception('XXX')
      # This should have created two log files, one specific to the current pid.
      self.assertEqual(os.listdir(tmpdir), ['logs'])
      cur_process_error_log_path = os.path.join(tmpdir, 'logs', 'exceptions.{}.log'.format(pid))
      self.assertTrue(os.path.isfile(cur_process_error_log_path))
      shared_error_log_path = os.path.join(tmpdir, 'logs', 'exceptions.log')
      self.assertTrue(os.path.isfile(shared_error_log_path))
      # We only logged a single error, so the files should both contain only that single log entry.
      err_rx = """\
timestamp: ([^\n]+)
args: ([^\n]+)
pid: {pid}
XXX
""".format(pid=re.escape(str(pid)))
      with open(cur_process_error_log_path, 'r') as cur_pid_file:
        self.assertRegexpMatches(cur_pid_file.read(), err_rx)
      with open(shared_error_log_path, 'r') as shared_log_file:
        self.assertRegexpMatches(shared_log_file.read(), err_rx)
      # Test that try_find_exception_logs_for_pids() can find the pid file for the current pid.
      log_contents = assert_single_element(sink.try_find_exception_logs_for_pids([os.getpid()]))
      self.assertRegexpMatches(log_contents, err_rx)

  def test_backup_logging_on_fatal_error(self):
    sink = self._gen_sink_subclass()
    with self.captured_logging(level=logging.ERROR) as captured:
      with temporary_dir() as tmpdir:
        sink.reset_log_location(tmpdir, os.getpid())
        with mock.patch.object(sink, '_format_exception_message', autospec=sink) as mock_write:
          mock_write.side_effect = Exception('fake write failure')
          sink.log_exception('XXX')
    single_error_logged = str(assert_single_element(captured.errors()))
    err_rx = re.escape("pants.base.exception_sink: Problem logging original exception: fake write failure. The original error message was:\nXXX")
    self.assertRegexpMatches(single_error_logged, err_rx)
