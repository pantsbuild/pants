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

__author__ = 'John Sirois'

from twitter.pants import is_python
from twitter.pants.base.builder import Builder
from twitter.pants.targets import PythonBinary, PythonTests, PythonTestSuite

from binary_builder import PythonBinaryBuilder
from test_builder import PythonTestBuilder
from lint_builder import PythonLintBuilder

class PythonBuilder(Builder):
  def __init__(self, ferror, root_dir):
    Builder.__init__(self, ferror, root_dir)

  def build(self, targets, args):
    test_targets = []
    binary_targets = []

    for target in targets:
      assert is_python(target), "PythonBuilder can only build PythonTargets, given %s" % str(target)

    if 'pylint' in args:
      real_args = list(args)
      real_args.remove('pylint')
      for target in targets:
        PythonLintBuilder([target], real_args, self.root_dir).run()
      return 0

    # PythonBuilder supports PythonTests and PythonBinaries
    for target in targets:
      if isinstance(target, PythonTests) or isinstance(target, PythonTestSuite):
        test_targets.append(target)
      elif isinstance(target, PythonBinary):
        binary_targets.append(target)

    rv = PythonTestBuilder(test_targets, args, self.root_dir).run()
    if rv != 0: return rv

    for binary_target in binary_targets:
      rv = PythonBinaryBuilder(binary_target, args, self.root_dir).run()
      if rv != 0: return rv

    return 0
