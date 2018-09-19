# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import unittest

from pants.bin.exception_sink import ExceptionSink


class TestExceptionSink(unittest.TestCase):

  def _timestamp_log_rx(self, err_rx):
    # NB: This is a very light method of testing that the timestamp is a valid timestamp instead of
    # nonsense -- this can be expanded later if we need to verify correctness of the timestamps
    # logged in the future.
    return r'\(at [0-9].*?[0-9]\) {}'.format(err_rx)

  def test_unset_destination(self):
    sink = ExceptionSink()
    err_rx = re.escape(
      'The exception sink path was not yet initialized with set_destination().')
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, self._timestamp_log_rx(err_rx)):
      sink.get_destination()

  def test_set_invalid_destination(self):
    sink = ExceptionSink()
    err_rx = re.escape(
      "The provided exception sink path at '/does/not/exist' is not a writable directory.")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, self._timestamp_log_rx(err_rx)):
      sink.set_destination('/does/not/exist')
    err_rx = re.escape(
      "The provided exception sink path at '/' is not a writable directory.")
    with self.assertRaisesRegexp(ExceptionSink.ExceptionSinkError, self._timestamp_log_rx(err_rx)):
      sink.set_destination('/')

  def test_retrieve_destination(self):
    sink = ExceptionSink()
    pwd = os.getcwd()
    sink.set_destination(pwd)
    self.assertEqual(pwd, sink.get_destination())
