# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.util.retry import retry_on_exception


class RetryTest(unittest.TestCase):
  @mock.patch('time.sleep', autospec=True, spec_set=True)
  def test_retry_on_exception(self, mock_sleep):
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

  @mock.patch('time.sleep', autospec=True, spec_set=True)
  def test_retry_on_exception_eventual_success(self, mock_sleep):
    broken_func = mock.Mock()
    broken_func.side_effect = [IOError('broken'), IOError('broken'), 'works now']

    retry_on_exception(broken_func, 3, (IOError,))

    self.assertEquals(broken_func.call_count, 3)

  @mock.patch('time.sleep', autospec=True, spec_set=True)
  def test_retry_on_exception_not_caught(self, mock_sleep):
    broken_func = mock.Mock()
    broken_func.side_effect = IOError('broken')

    with self.assertRaises(IOError):
      retry_on_exception(broken_func, 3, (TypeError,))

    self.assertEquals(broken_func.call_count, 1)

  @mock.patch('time.sleep', autospec=True, spec_set=True)
  def test_retry_default_backoff(self, mock_sleep):
    broken_func = mock.Mock()
    broken_func.side_effect = IOError('broken')

    with self.assertRaises(IOError):
      retry_on_exception(broken_func, 4, (IOError,))

    mock_sleep.assert_has_calls((
      mock.call(0),
      mock.call(0),
      mock.call(0)
    ))
