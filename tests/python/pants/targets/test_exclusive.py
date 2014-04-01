# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.config import Config
from pants.goal import Context
from pants.tasks.check_exclusives import CheckExclusives
from pants.testutils import MockTarget
from pants.testutils.base_mock_target_test import BaseMockTargetTest


class ExclusivesTargetTest(BaseMockTargetTest):
  """Test exclusives propagation in the dependency graph"""

  @classmethod
  def setUpClass(cls):
     cls.config = Config.load()

  def setupTargets(self):
    a = MockTarget('a', exclusives={'a': '1', 'b': '1'})
    b = MockTarget('b', exclusives={'a': '1'})
    c = MockTarget('c', exclusives = {'a': '2'})
    d = MockTarget('d', dependencies=[a, b])
    e = MockTarget('e', dependencies=[a, c], exclusives={'c': '1'})
    return a, b, c, d, e

  def testPropagation(self):
    a, b, c, d, e = self.setupTargets()
    d_excl = d.get_all_exclusives()
    self.assertEquals(d_excl['a'], set(['1']))
    e_excl = e.get_all_exclusives()
    self.assertEquals(e_excl['a'], set(['1', '2']))

  def testPartitioning(self):
    # Target e has conflicts; in this test, we want to check that partitioning
    # of valid targets works to prevent conflicts in chunks, so we only use a-d.
    a, b, c, d, _ = self.setupTargets()
    context = Context(ExclusivesTargetTest.config, options={}, run_tracker=None, target_roots=[a, b, c, d])
    context.products.require_data('exclusives_groups')
    check_exclusives_task = CheckExclusives(context, signal_error=True)
    check_exclusives_task.execute([a, b, c, d])
    egroups = context.products.get_data('exclusives_groups')
    self.assertEquals(egroups.get_targets_for_group_key("a=1"), set([a, b, d]))
    self.assertEquals(egroups.get_targets_for_group_key("a=2"), set([c]))
