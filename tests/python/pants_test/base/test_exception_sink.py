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

  def test_unset_destination(self):
    self.assertEqual(os.getcwd(), ExceptionSink().get_destination())

  def test_set_invalid_destination(self):
    sink = ExceptionSink()
    err_rx = re.escape(
      "The provided exception sink path at '/does/not/exist' is not a writable directory.")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.set_destination('/does/not/exist')
    err_rx = re.escape(
      "The provided exception sink path at '/' is not a writable directory.")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, err_rx):
      sink.set_destination('/')

  def test_retrieve_destination(self):
    sink = ExceptionSink()

    with temporary_dir() as tmpdir:
      sink.set_destination(tmpdir)
      self.assertEqual(tmpdir, sink.get_destination())

  def test_log_exception(self):
    with temporary_dir() as tmpdir:
      ExceptionSink(tmpdir).log_exception('XXX')
      self.assertEqual(os.listdir(tmpdir), ['logs'])
      expected_exception_log_file_path = os.path.join(tmpdir, 'logs', 'exceptions.log')
      self.assertTrue(os.path.isfile(expected_exception_log_file_path))
      with open(expected_exception_log_file_path, 'r') as exceptions_log_file:
        self.assertRegexpMatches(exceptions_log_file.read(), """\
timestamp: ([^\n]+)
args: ([^\n]+)
pid: ([^\n]+)
XXX
""")

  def test_backup_logging_on_fatal_error(self):
    with self.captured_logging(level=logging.ERROR) as captured:
      with temporary_dir() as tmpdir:
        exc_log_path = os.path.join(tmpdir, 'logs', 'exceptions.log')
        touch(exc_log_path)
        # Make the exception log file unreadable.
        os.chmod(exc_log_path, 0)
        ExceptionSink(tmpdir).log_exception('XXX')
    single_error_logged = str(assert_single_element(captured.errors()))
    expected_rx_str = (
      re.escape("pants.base.exception_sink: Problem logging original exception: [Errno 13] Permission denied: '") +
      '.*' +
      re.escape("/logs/exceptions.log'"))
    self.assertRegexpMatches(single_error_logged, expected_rx_str)
