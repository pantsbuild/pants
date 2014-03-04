# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import sys
import threading
import unittest

import pytest

from Queue import Empty, Queue

from twitter.pants.tasks.test_base import prepare_task
from twitter.pants.tasks.console_task import ConsoleTask


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
