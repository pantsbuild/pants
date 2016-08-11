# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import unittest

import mock

from pants.process.xargs import Xargs


class XargsTest(unittest.TestCase):
  def setUp(self):
    self.call = mock.Mock()
    self.xargs = Xargs(self.call)

  def test_execute_nosplit_success(self):
    self.call.return_value = 0

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

    self.call.assert_called_once_with(['one', 'two', 'three', 'four'])

  def test_execute_nosplit_raise(self):
    exception = Exception()
    self.call.side_effect = exception

    with self.assertRaises(Exception) as raised:
      self.xargs.execute(['one', 'two', 'three', 'four'])

    self.call.assert_called_once_with(['one', 'two', 'three', 'four'])
    self.assertIs(exception, raised.exception)

  def test_execute_nosplit_fail(self):
    self.call.return_value = 42

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

    self.call.assert_called_once_with(['one', 'two', 'three', 'four'])

  TOO_BIG = OSError(errno.E2BIG, os.strerror(errno.E2BIG))

  def test_execute_split(self):
    self.call.side_effect = (self.TOO_BIG, 0, 0)

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

    self.assertEqual([mock.call(['one', 'two', 'three', 'four']),
                      mock.call(['one', 'two']),
                      mock.call(['three', 'four'])],
                     self.call.mock_calls)

  def test_execute_uneven(self):
    self.call.side_effect = (self.TOO_BIG, 0, 0)

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three']))

    self.assertEqual(3, self.call.call_count)
    self.assertEqual(mock.call(['one', 'two', 'three']),
                     self.call.mock_calls[0])

    self.assertEqual(sorted((mock.call(['one']), mock.call(['two', 'three']))),
                     sorted(self.call.mock_calls[1:]))

  def test_execute_split_multirecurse(self):
    self.call.side_effect = (self.TOO_BIG, self.TOO_BIG, 0, 0, 0)

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

    self.assertEqual([mock.call(['one', 'two', 'three', 'four']),
                      mock.call(['one', 'two']),
                      mock.call(['one']),
                      mock.call(['two']),
                      mock.call(['three', 'four'])],
                     self.call.mock_calls)

  def test_execute_split_fail_fast(self):
    self.call.side_effect = (self.TOO_BIG, 42)

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

    self.assertEqual([mock.call(['one', 'two', 'three', 'four']),
                      mock.call(['one', 'two'])],
                     self.call.mock_calls)

  def test_execute_split_fail_slow(self):
    self.call.side_effect = (self.TOO_BIG, 0, 42)

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

    self.assertEqual([mock.call(['one', 'two', 'three', 'four']),
                      mock.call(['one', 'two']),
                      mock.call(['three', 'four'])],
                     self.call.mock_calls)
