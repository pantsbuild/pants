# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants_test.base_test import BaseTest


class ContextTest(BaseTest):
  def test_dependents_empty(self):
    context = self.context()
    dependees = context.dependents()
    self.assertEquals(0, len(dependees))

  def test_dependents_direct(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    e = self.make_target('e', dependencies=[d])
    context = self.context(target_roots=[a, b, c, d, e])
    dependees = context.dependents(lambda t: t in set([e, c]))
    self.assertEquals(set([c]), dependees.pop(d))
    self.assertEquals(0, len(dependees))
