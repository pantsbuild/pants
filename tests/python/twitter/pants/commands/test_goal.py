# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.commands.goal import Goal, GoalError


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
