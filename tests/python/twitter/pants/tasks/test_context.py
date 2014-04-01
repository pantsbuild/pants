# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.config import Config
from pants.goal import Context
from pants.testutils import MockTarget
from pants.testutils.base_mock_target_test import BaseMockTargetTest


class ContextTest(BaseMockTargetTest):
  @classmethod
  def setUpClass(cls):
    cls.config = Config.load()

  @classmethod
  def create_context(cls, **kwargs):
    return Context(cls.config, run_tracker=None, **kwargs)

  def test_dependents_empty(self):
    context = self.create_context(options={}, target_roots=[])
    dependees = context.dependents()
    self.assertEquals(0, len(dependees))

  def test_dependents_direct(self):
    a = MockTarget('a')
    b = MockTarget('b', [a])
    c = MockTarget('c', [b])
    d = MockTarget('d', [c, a])
    e = MockTarget('e', [d])
    context = self.create_context(options={}, target_roots=[a, b, c, d, e])
    dependees = context.dependents(lambda t: t in set([e, c]))
    self.assertEquals(set([c]), dependees.pop(d))
    self.assertEquals(0, len(dependees))
