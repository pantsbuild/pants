# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.util.retry import retry_on_exception


class RetryTest(unittest.TestCase):
  def test_retry_on_exception(self):
    broken_func = mock.Mock()
    broken_func.side_effect = IOError('broken')

    with self.assertRaises(IOError):
      retry_on_exception(broken_func, 3, (IOError,))

    self.assertEquals(broken_func.call_count, 3)

  def test_retry_on_exception_immediate_success(self):
    working_func = mock.Mock()
    working_func.return_value = 'works'

    self.assertEquals(retry_on_exception(working_func, 3, (IOError,)), 'works')
    self.assertEquals(working_func.call_count, 1)

  def test_retry_on_exception_eventual_success(self):
    broken_func = mock.Mock()
    broken_func.side_effect = [IOError('broken'), IOError('broken'), 'works now']

    retry_on_exception(broken_func, 3, (IOError,))

    self.assertEquals(broken_func.call_count, 3)

  def test_retry_on_exception_not_caught(self):
    broken_func = mock.Mock()
    broken_func.side_effect = IOError('broken')

    with self.assertRaises(IOError):
      retry_on_exception(broken_func, 3, (TypeError,))

    self.assertEquals(broken_func.call_count, 1)
