# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from builtins import open, str

from pants.base.exiter import Exiter
from pants.util.contextutil import temporary_dir
from pants_test.option.util.fakes import create_options
from pants_test.test_base import TestBase


class ExiterTest(TestBase):

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

  def test_log_exception_no_workdir(self):
    with self.captured_logging(level=logging.ERROR) as captured:
      exiter = Exiter()
      exiter.log_exception('test')
    all_errors = list(captured.errors())
    self.assertTrue(len(all_errors) == 1)
    single_error = all_errors[0]
    expected_msg = (
      'pants.base.exiter: Problem logging original exception: no workdir or self._workdir was set to log exceptions to. message was: test')
    self.assertEqual(expected_msg, str(single_error))

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
