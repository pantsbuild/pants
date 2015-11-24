# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import threading
from Queue import Empty, Queue

from pants.task.console_task import ConsoleTask
from pants_test.tasks.task_test_base import TaskTestBase


class ConsoleTaskTest(TaskTestBase):
  class Infinite(ConsoleTask):
    def __init__(self, *args, **kwargs):
      super(ConsoleTaskTest.Infinite, self).__init__(*args, **kwargs)
      self.halt = threading.Event()

    def console_output(self, _):
      while not self.halt.isSet():
        yield 'jake'

    def stop(self):
      self.halt.set()

  @classmethod
  def task_type(cls):
    return cls.Infinite

  def test_sigpipe(self):
    r, w = os.pipe()
    outstream = os.fdopen(w, 'w')
    task = self.create_task(self.context(console_outstream=outstream))
    raised = Queue(maxsize=1)

    def execute():
      try:
        task.execute()
      except IOError as e:
        raised.put(e)

    execution = threading.Thread(target=execute, name='ConsoleTaskTestBase_sigpipe')
    execution.setDaemon(True)
    execution.start()
    try:
      data = os.read(r, 5)
      self.assertEqual('jake\n', data)
      os.close(r)
    finally:
      task.stop()
      execution.join()

    with self.assertRaises(Empty):
      e = raised.get_nowait()

      # Instead of taking the generic assertRaises raises message, provide a more detailed failure
      # message that shows exactly what untrapped error was on the queue.
      self.fail('task raised {0}'.format(e))
