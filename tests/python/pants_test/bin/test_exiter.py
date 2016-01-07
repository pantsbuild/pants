# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.bin.exiter import Exiter
from pants.util.contextutil import temporary_dir
from pants_test.option.util.fakes import create_options


class ExiterTest(unittest.TestCase):

  def test_log_exception(self):
    with temporary_dir() as workdir:
      exiter = Exiter()
      exiter.apply_options(create_options({ '': {
        'print_exception_stacktrace': True,
        'pants_workdir': workdir}
      }))
      exiter._log_exception('test-data')
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
        self.assertIn('test-data', msg)
