# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import re
from builtins import open, str

from pants.base.exception_sink import ExceptionSink
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.test_base import TestBase


class TestExceptionSink(TestBase):

  def _gen_sink_subclass(self):
    # Avoid modifying global state by generating a subclass.
    class AnonymousSink(ExceptionSink): pass
    return AnonymousSink

  def test_unset_destination(self):
    self.assertEqual(os.getcwd(), self._gen_sink_subclass().get_destination())

  def test_set_invalid_destination(self):
    sink = self._gen_sink_subclass()
    err_rx = re.escape(
      "The provided exception sink path at '/does/not/exist' is not a writable directory.")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.set_destination('/does/not/exist')
    err_rx = re.escape(
      "The provided exception sink path at '/' is not a writable directory.")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.set_destination('/')

  def test_retrieve_destination(self):
    sink = self._gen_sink_subclass()

    with temporary_dir() as tmpdir:
      sink.set_destination(tmpdir)
      self.assertEqual(tmpdir, sink.get_destination())

  def test_log_exception(self):
    sink = self._gen_sink_subclass()
    pid = os.getpid()
    with temporary_dir() as tmpdir:
      # Check that tmpdir exists, and log an exception into that directory.
      sink.set_destination(tmpdir)
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

  def test_backup_logging_on_fatal_error(self):
    sink = self._gen_sink_subclass()
    with self.captured_logging(level=logging.ERROR) as captured:
      with temporary_dir() as tmpdir:
        exc_log_path = os.path.join(tmpdir, 'logs', 'exceptions.log')
        touch(exc_log_path)
        # Make the exception log file unreadable.
        os.chmod(exc_log_path, 0)
        sink.set_destination(tmpdir)
        sink.log_exception('XXX')
    single_error_logged = str(assert_single_element(captured.errors()))
    expected_rx_str = (
      re.escape("pants.base.exception_sink: Problem logging original exception: [Errno 13] Permission denied: '") +
      '.*' +
      re.escape("/logs/exceptions.log'"))
    self.assertRegexpMatches(single_error_logged, expected_rx_str)
