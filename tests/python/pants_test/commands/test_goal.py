# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.register import register_goals
from pants.commands.goal import Goal
from pants.goal.phase import Phase
from pants_test.base_test import BaseTest


class GoalTest(BaseTest):

  def setUp(self):
    super(GoalTest, self).setUp()
    # Have to load in goals, because parse_args requires Phase.all() now.
    # Fortunately, we only have to load in the goals we're actually using below, so the goals in the
    # core register are sufficient.
    register_goals()

  def tearDown(self):
    super(GoalTest, self).tearDown()
    Phase.clear()

  def assert_result(self, goals, specs, args):
    g, s = Goal.parse_args(args)
    self.assertEquals((goals, specs), (list(g), list(s)))

  def test_top_level_dir(self):
    self.create_dir('topleveldir')
    self.create_file('topleveldir/BUILD', contents='')
    self.assert_result(goals=[], specs=['topleveldir'], args=['topleveldir'])

  def test_arg_ambiguity(self):
    self.create_dir('compile')
    self.create_file('compile/BUILD', contents='')
    self.assert_result(goals=['compile'], specs=[], args=['compile'])
    # Only end up with one 'compile' here, because goals and specs are sets.
    self.assert_result(goals=['compile'], specs=[], args=['compile', 'compile'])
    self.assert_result(goals=['compile'], specs=['compile'], args=['compile', '--', 'compile'])

    try:
      self.assert_result(goals=['compile'], specs=[], args=['compile', 'spec:', '--', 'compile'])
      self.fail('Expected mixed specs and goals to the left of an explicit multi-goal sep (--) to '
                'be rejected.')
    except Goal.IntermixedArgumentsError:
      pass # expected

    self.assert_result(goals=['bundle', 'compile'], specs=['run'],
                       args=['bundle', 'compile', '--', 'run'])

  def test_parse_args(self):
    self.assert_result(goals=[], specs=[], args=[])
    self.assert_result(goals=[], specs=[], args=['--'])
    self.assert_result(goals=[], specs=[], args=['-v', '--help'])

    self.assert_result(goals=['compile'], specs=[], args=['compile', '--log'])
    self.assert_result(goals=['compile', 'test'], specs=[], args=['compile', 'test'])
    self.assert_result(goals=['compile', 'test'], specs=[], args=['compile', '-v', 'test'])

    self.assert_result(goals=[], specs=['resolve'], args=['--', 'resolve', '--ivy-open'])
    self.assert_result(goals=['test'], specs=['resolve'], args=['test', '--', 'resolve',
                                                                '--ivy-open'])

    try:
      Goal.parse_args(['test', 'lib:all', '--', 'resolve'])
      self.fail('Expected mixed specs and goals to the left of an explicit '
                'multi-goal sep (--) to be rejected.')
    except Goal.IntermixedArgumentsError:
      pass # expected

    try:
      Goal.parse_args(['resolve', 'lib/all', 'test', '--'])
      self.fail('Expected mixed specs and goals to the left of an explicit '
                'multi-goal sep (--) to be rejected.')
    except Goal.IntermixedArgumentsError:
      pass # expected

    self.assert_result(goals=['test'], specs=['lib:all'], args=['lib:all', '-v', 'test'])
    self.assert_result(goals=['test'], specs=['lib/'], args=['-v', 'test', 'lib/'])
    self.assert_result(goals=['test'], specs=['lib/io:sound'], args=['test', '-v', 'lib/io:sound'])
    self.assert_result(goals=['test'], specs=['lib:all'], args=['-h', 'test', '-v', 'lib:all',
                                                                '-x'])
