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

  def test_targets_order(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    context = self.context(target_roots=[d])
    self.assertEquals([d, c, b, a], context.targets())
    e = self.make_target('e', dependencies=[d])
    context = self.context(target_roots=[e])
    self.assertEquals([e, d, c, b, a], context.targets())
    f = self.make_target('f', dependencies=[a])
    context = self.context(target_roots=[f])
    self.assertEquals([f, a], context.targets())
    g = self.make_target('g', dependencies=[a, c, d])
    context = self.context(target_roots=[g])
    self.assertEquals([g, a, c, b, d], context.targets())

  def test_targets_replace_targets(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])

    context = self.context(target_roots=[b])
    self.assertEquals([b, a], context.targets())
    context._replace_targets([a])
    self.assertEquals([a], context.targets())
    context._replace_targets([c])
    self.assertEquals([c, b, a], context.targets())