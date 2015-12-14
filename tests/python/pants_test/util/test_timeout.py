# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.timeout import Timeout, TimeoutReached


class FakeTimer(object):
  def __init__(self, seconds, handler):
    self._seconds = seconds
    self._handler = handler
    self._clock = 0
    self._started = False

  def cancel(self):
    pass

  def start(self):
    self._started = True

  def move_clock_forward(self, seconds):
    if not self._started:
      raise Exception("Timer not started but clock moved forward")

    self._clock += seconds
    if self._clock > self._seconds:
      self._handler()


class TestTimeout(unittest.TestCase):
  def setUp(self):
    super(TestTimeout, self).setUp()
    self._fake_timer = None
    self._aborted = False

  def _abort_handler(self):
    self._aborted = True

  def _make_fake_timer(self, seconds, handler):
    self._fake_timer = FakeTimer(seconds, handler)
    return self._fake_timer

  def _move_clock_forward(self, seconds):
    if self._fake_timer is not None:
      self._fake_timer.move_clock_forward(seconds)

  def test_timeout_success(self):
    with Timeout(2, threading_timer=self._make_fake_timer, abort_handler=self._abort_handler):
      self._move_clock_forward(1)

    self.assertFalse(self._aborted)

  def test_timeout_failure(self):
    with self.assertRaises(TimeoutReached):
      with Timeout(2, threading_timer=self._make_fake_timer, abort_handler=self._abort_handler):
        self._move_clock_forward(3)

    self.assertTrue(self._aborted)

  def test_timeout_none(self):
    with Timeout(None, threading_timer=self._make_fake_timer, abort_handler=self._abort_handler):
      self._move_clock_forward(3)

    self.assertFalse(self._aborted)

  def test_timeout_zero(self):
    with Timeout(0, threading_timer=self._make_fake_timer, abort_handler=self._abort_handler):
      self._move_clock_forward(3)

    self.assertFalse(self._aborted)
