# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os

import mox

from pants.process.xargs import Xargs


class XargsTest(mox.MoxTestBase):
  def setUp(self):
    super(XargsTest, self).setUp()
    self.call = self.mox.CreateMockAnything()
    self.xargs = Xargs(self.call)

  def test_execute_nosplit_success(self):
    self.call(['one', 'two', 'three', 'four']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_nosplit_raise(self):
    exception = Exception()

    self.call(['one', 'two', 'three', 'four']).AndRaise(exception)
    self.mox.ReplayAll()

    with self.assertRaises(Exception) as raised:
      self.xargs.execute(['one', 'two', 'three', 'four'])
    self.assertIs(exception, raised.exception)

  def test_execute_nosplit_fail(self):
    self.call(['one', 'two', 'three', 'four']).AndReturn(42)
    self.mox.ReplayAll()

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

  TOO_BIG = OSError(errno.E2BIG, os.strerror(errno.E2BIG))

  def test_execute_split(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndReturn(0)
    self.call(['three', 'four']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_uneven(self):
    self.call(['one', 'two', 'three']).AndRaise(self.TOO_BIG)
    # TODO(John Sirois): We really don't care if the 1st call gets 1 argument or 2, we just
    # care that all arguments get passed just once via exactly 2 rounds of call - consider making
    # this test less brittle to changes in the chunking logic.
    self.call(['one']).AndReturn(0)
    self.call(['two', 'three']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three']))

  def test_execute_split_multirecurse(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndRaise(self.TOO_BIG)
    self.call(['one']).AndReturn(0)
    self.call(['two']).AndReturn(0)
    self.call(['three', 'four']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_split_fail_fast(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndReturn(42)
    self.mox.ReplayAll()

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_split_fail_slow(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndReturn(0)
    self.call(['three', 'four']).AndReturn(42)
    self.mox.ReplayAll()

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))
