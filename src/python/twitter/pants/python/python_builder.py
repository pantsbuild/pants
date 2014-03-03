# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

from twitter.common.python.interpreter import PythonInterpreter

from twitter.pants.targets.python_binary import PythonBinary
from twitter.pants.targets.python_tests import PythonTests, PythonTestSuite

from .binary_builder import PythonBinaryBuilder
from .test_builder import PythonTestBuilder


class PythonBuilder(object):
  def __init__(self, run_tracker, root_dir):
    self._root_dir = root_dir
    self._run_tracker = run_tracker

  def build(self, targets, args, interpreter=None, conn_timeout=None):
    test_targets = []
    binary_targets = []
    interpreter = interpreter or PythonInterpreter.get()

    for target in targets:
      assert target.is_python, "PythonBuilder can only build PythonTargets, given %s" % str(target)

    # PythonBuilder supports PythonTests and PythonBinaries
    for target in targets:
      if isinstance(target, PythonTests) or isinstance(target, PythonTestSuite):
        test_targets.append(target)
      elif isinstance(target, PythonBinary):
        binary_targets.append(target)

    rv = PythonTestBuilder(
        test_targets,
        args,
        self._root_dir,
        interpreter=interpreter,
        conn_timeout=conn_timeout).run()
    if rv != 0:
      return rv

    for binary_target in binary_targets:
      rv = PythonBinaryBuilder(
          binary_target,
          self._root_dir,
          self._run_tracker,
          interpreter=interpreter,
          conn_timeout=conn_timeout).run()
      if rv != 0:
        return rv

    return 0
