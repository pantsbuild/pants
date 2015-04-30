# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading
import unittest

from pants.base.worker_pool import Work, WorkerPool
from pants.base.workunit import WorkUnit
from pants.util.contextutil import temporary_dir


class FakeRunTracker(object):
  def register_thread(self, one):
    pass


def keyboard_interrupt_raiser():
  raise KeyboardInterrupt()


class WorkerPoolTest(unittest.TestCase):
  def test_keyboard_interrupts_propagated(self):
    condition = threading.Condition()
    condition.acquire()
    with self.assertRaises(KeyboardInterrupt):
      with temporary_dir() as rundir:
        pool = WorkerPool(WorkUnit(rundir, None, "work"), FakeRunTracker(), 1)
        try:
          pool.submit_async_work(Work(keyboard_interrupt_raiser, [()]))
          condition.wait(2)
        finally:
          pool.abort()
