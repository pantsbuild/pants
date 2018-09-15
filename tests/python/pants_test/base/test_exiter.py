# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import unittest
from builtins import open

from pants.base.exiter import Exiter
from pants.util.contextutil import temporary_dir
from pants_test.option.util.fakes import create_options


class ExiterTest(unittest.TestCase):

  def test_log_exception_no_workdir(self):
    exiter = Exiter()
    expected_rx_str = re.escape(
      'no workdir or self._workdir was set to log exceptions to. message was: test')
    with self.assertRaisesRegexp(Exception, expected_rx_str):
      exiter.log_exception('test')

  def _assert_exception_log_contents(self, exiter, workdir=None):
    log_string = 'test-data'
    exiter.log_exception(log_string, workdir=workdir)
    workdir = workdir or exiter._workdir
    output_path = os.path.join(workdir, 'logs', 'exceptions.log')
    self.assertTrue(os.path.exists(output_path))
    with open(output_path, 'r') as exception_log:
      timestamp = exception_log.readline()
      args = exception_log.readline()
      pid = exception_log.readline()
      msg = exception_log.readline()
      self.assertIn('timestamp: ', timestamp)
      self.assertIn('args: [', args)
      self.assertIn('pid: {}'.format(os.getpid()), pid)
      self.assertIn(log_string, msg)

  def test_log_exception_given_workdir(self):
    with temporary_dir() as workdir:
      exiter = Exiter()
      self._assert_exception_log_contents(exiter, workdir=workdir)

  def test_log_exception_workdir_apply_options(self):
    with temporary_dir() as workdir:
      exiter = Exiter()
      exiter.apply_options(create_options({ '': {
        # TODO: test both values of this option!
        'print_exception_stacktrace': True,
        'pants_workdir': workdir}
      }))
      self._assert_exception_log_contents(exiter)
