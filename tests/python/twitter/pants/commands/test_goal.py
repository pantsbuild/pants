# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import unittest

from twitter.pants.commands.goal import Goal, GoalError

class GoalTest(unittest.TestCase):
  def test_parse_args(self):
    def assert_result(goals, specs, args):
      g, s = Goal.parse_args(args)
      self.assertEquals((goals, specs), (list(g), list(s)))

    assert_result(goals=[], specs=[], args=[])
    assert_result(goals=[], specs=[], args=['--'])
    assert_result(goals=[], specs=[], args=['-v', '--help'])

    assert_result(goals=['compile'], specs=[], args=['compile', '--log'])
    assert_result(goals=['compile', 'test'], specs=[], args=['compile', 'test'])
    assert_result(goals=['compile', 'test'], specs=[], args=['compile', '-v', 'test'])

    assert_result(goals=[], specs=['resolve'], args=['--', 'resolve', '--ivy-open'])
    assert_result(goals=['test'], specs=['resolve'], args=['test', '--', 'resolve', '--ivy-open'])

    try:
      Goal.parse_args(['test', 'lib:all', '--', 'resolve'])
      self.fail('Expected mixed specs and goals to the left of an explicit '
                'multi-goal sep (--) to be rejected.')
    except GoalError:
      pass # expected

    try:
      Goal.parse_args(['resolve', 'lib/all', 'test', '--'])
      self.fail('Expected mixed specs and goals to the left of an explicit '
                'multi-goal sep (--) to be rejected.')
    except GoalError:
      pass # expected

    assert_result(goals=['test'], specs=['lib:all'], args=['lib:all', '-v', 'test'])
    assert_result(goals=['test'], specs=['lib/'], args=['-v', 'test', 'lib/'])
    assert_result(goals=['test'], specs=['lib/io:sound'], args=['test', '-v', 'lib/io:sound'])
    assert_result(goals=['test'], specs=['lib:all'], args=['-h', 'test', '-v', 'lib:all', '-x'])

