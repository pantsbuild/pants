# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.deadline import Timeout, deadline, wait_until


def raiser():
  raise NotImplementedError()


class TestDeadline(unittest.TestCase):
  def test_wait_until(self):
    # This will exercise all of wait_until -> until -> deadline.
    with self.assertRaises(Timeout):
      wait_until(lambda: False, .1)

  def test_deadline_propagate(self):
    with self.assertRaises(NotImplementedError):
      deadline(raiser, 1, propagate=True)

  def test_deadline_doesnt_propagate(self):
    # Since the closure dies via raising an exception, it won't technically complete in the
    # allotted time and should raise Timeout (and not NotImplementedError with propagate=False).
    with self.assertRaises(Timeout):
      deadline(raiser, 1, propagate=False)
