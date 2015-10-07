# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading

import mox

from pants.util.timeout import Timeout, TimeoutReached


class TestTimeout(mox.MoxTestBase):
  def setUp(self):
    super(TestTimeout, self).setUp()
    def empty_handler():
      pass

    self._handler = empty_handler

  def set_handler(self, dummy, handler):
    self._handler = handler

  def test_timeout_success(self):
    self.mox.StubOutWithMock(threading, 'Timer')
    threading.Timer(2, mox.IgnoreArg()).WithSideEffects(self.set_handler)
    self.mox.ReplayAll()

    with Timeout(2):
      pass

  def test_timeout_failure(self):
    self.mox.StubOutWithMock(threading, 'Timer')
    threading.Timer(1, mox.IgnoreArg()).WithSideEffects(self.set_handler)
    self.mox.ReplayAll()

    with self.assertRaises(TimeoutReached):
      with Timeout(1):
        self._handler()

  def test_timeout_none(self):
    self.mox.StubOutWithMock(threading, 'Timer')
    self.mox.ReplayAll()

    with Timeout(None):
      pass

  def test_timeout_zero(self):
    self.mox.StubOutWithMock(threading, 'Timer')
    self.mox.ReplayAll()

    with Timeout(0):
      self._handler()
