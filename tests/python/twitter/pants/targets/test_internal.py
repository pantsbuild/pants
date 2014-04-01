# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.parse_context import ParseContext
from pants.base.target import Target, TargetDefinitionException
from pants.targets.internal import InternalTarget
from pants.testutils import MockTarget
from pants.testutils.base_mock_target_test import BaseMockTargetTest


class InternalTargetTest(BaseMockTargetTest):

  def test_validation(self):
    with ParseContext.temp('InternalTargetTest/test_validation'):
      InternalTarget(name="valid", dependencies=None)
      self.assertRaises(TargetDefinitionException, InternalTarget,
                        name=1, dependencies=None)

      InternalTarget(name="valid2", dependencies=Target(name='mybird'))
      self.assertRaises(TargetDefinitionException, InternalTarget,
                        name='valid3', dependencies=1)

  def test_detect_cycle_direct(self):
    a = MockTarget('a')

    # no cycles yet
    InternalTarget.sort_targets([a])
    a.update_dependencies([a])
    try:
      InternalTarget.sort_targets([a])
      self.fail("Expected a cycle to be detected")
    except InternalTarget.CycleException:
      # expected
      pass

  def test_detect_cycle_indirect(self):
    c = MockTarget('c')
    b = MockTarget('b', [c])
    a = MockTarget('a', [c, b])

    # no cycles yet
    InternalTarget.sort_targets([a])

    c.update_dependencies([a])
    try:
      InternalTarget.sort_targets([a])
      self.fail("Expected a cycle to be detected")
    except InternalTarget.CycleException:
      # expected
      pass

  def testSort(self):
    a = MockTarget('a', [])
    b = MockTarget('b', [a])
    c = MockTarget('c', [b])
    d = MockTarget('d', [c, a])
    e = MockTarget('e', [d])

    self.assertEquals(InternalTarget.sort_targets([a,b,c,d,e]), [e,d,c,b,a])
    self.assertEquals(InternalTarget.sort_targets([b,d,a,e,c]), [e,d,c,b,a])
    self.assertEquals(InternalTarget.sort_targets([e,d,c,b,a]), [e,d,c,b,a])
