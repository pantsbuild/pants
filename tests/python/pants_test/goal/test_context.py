# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.address import Address
from pants.build_graph.target import Target
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
    dependees = context.dependents(lambda t: t in {e, c})
    self.assertEquals({c}, dependees.pop(d))
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

  def test_targets_synthetic(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    context = self.context(target_roots=[c])
    self.assertEquals([c, b, a], context.targets())

    syn_b = context.add_new_target(Address.parse('syn_b'), Target, derived_from=b)
    context.add_new_target(Address.parse('syn_d'), Target, derived_from=d)
    # We expect syn_b to be included now since it has been synthesized during this run from an
    # in-play target.
    self.assertEquals([c, b, a, syn_b], context.targets())

    # And verify the predicate operates over both normal and synthetic targets.
    self.assertEquals([syn_b], context.targets(lambda t: t.derived_from != t))
    self.assertEquals([c, b, a], context.targets(lambda t: t.derived_from == t))

  def test_targets_includes_synthetic_dependencies(self):
    a = self.make_target('a')
    b = self.make_target('b')
    context = self.context(target_roots=[b])
    self.assertEquals([b], context.targets())

    syn_with_deps = context.add_new_target(Address.parse('syn_with_deps'),
                                           Target,
                                           derived_from=b,
                                           dependencies=[a])

    self.assertEquals([b, syn_with_deps, a], context.targets())

  def test_targets_ignore_synthetics_with_no_derived_from_not_injected_into_graph(self):
    a = self.make_target('a')
    b = self.make_target('b')
    context = self.context(target_roots=[b])
    self.assertEquals([b], context.targets())

    context.add_new_target(Address.parse('syn_with_deps'), Target, dependencies=[a])
    self.assertEquals([b], context.targets())

  def test_targets_include_synthetics_with_no_derived_from_injected_into_graph(self):
    a = self.make_target('a')
    b = self.make_target('b')
    context = self.context(target_roots=[b])
    self.assertEquals([b], context.targets())

    syn_with_deps = context.add_new_target(Address.parse('syn_with_deps'), Target, dependencies=[a])
    b.inject_dependency(syn_with_deps.address)

    self.assertEquals([b, syn_with_deps, a], context.targets())
