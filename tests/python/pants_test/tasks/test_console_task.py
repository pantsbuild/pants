# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import sys
import threading
import unittest
from Queue import Empty, Queue

import pytest

from pants.tasks.console_task import ConsoleTask
from pants_test.tasks.test_base import prepare_task


class ConsoleTaskTest(unittest.TestCase):
  class Infinite(ConsoleTask):
    def __init__(self, context, outstream=sys.stdout):
      super(ConsoleTaskTest.Infinite, self).__init__(context, outstream)
      self.halt = threading.Event()

    def console_output(self, _):
      while not self.halt.isSet():
        yield 'jake'

    def stop(self):
      self.halt.set()

  def test_sigpipe(self):
    r, w = os.pipe()
    task = prepare_task(self.Infinite, outstream=os.fdopen(w, 'w'))

    raised = Queue(maxsize=1)

    def execute():
      try:
        task.execute([])
      except IOError as e:
        raised.put(e)

    execution = threading.Thread(target=execute, name='ConsoleTaskTest_sigpipe')
    execution.setDaemon(True)
    execution.start()
    try:
      data = os.read(r, 5)
      self.assertEqual('jake\n', data)
      os.close(r)
    finally:
      task.stop()
      execution.join()

    with pytest.raises(Empty):
      e = raised.get_nowait()

      # Instead of taking the generic pytest.raises message, provide a more detailed failure
      # message that shows exactly what untrapped error was on the queue.
      self.fail('task raised %s' % e)
