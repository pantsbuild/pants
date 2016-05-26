# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.build_graph.target import Target
from pants.build_graph.target_scopes import Scope, Scopes
from pants_test.base_test import BaseTest


class ScopesTest(BaseTest):

  def test_mixed_case(self):
    self.assertEquals(Scope('RUNTIME'), Scope('runtime'))
    self.assertNotEquals(Scope('RUNTIME'), Scope('COMPILE'))

  def test_default_parsing(self):
    equivalent_defaults = [
      (), None, '', 'default', 'DEFAULT', Scopes.DEFAULT, [None], (Scopes.DEFAULT), 'default ',
    ]

    expected = Scope(Scopes.DEFAULT)
    for i, scope in enumerate(equivalent_defaults):
      received = Scope(scope)
      self.assertEquals(expected, received, 'Expected scope {i}. {received} == {expected}'.format(
        i=i,
        received=received,
        expected=expected,
      ))

  def test_scope_inclusion(self):
    self.assertTrue(Scope('').in_scope())
    self.assertTrue(Scopes.DEFAULT.in_scope(include_scopes=None))
    self.assertTrue(Scopes.RUNTIME.in_scope(include_scopes=None))
    self.assertTrue(Scope('runtime test').in_scope(include_scopes=Scopes.TEST))
    self.assertFalse(Scope('').in_scope(include_scopes=Scopes.COMPILE))
    self.assertFalse(Scopes.RUNTIME.in_scope(include_scopes=Scopes.COMPILE))

  def test_scope_exclusion(self):
    self.assertTrue(Scopes.RUNTIME.in_scope(exclude_scopes=Scopes.COMPILE))
    self.assertFalse(Scopes.COMPILE.in_scope(exclude_scopes=Scopes.COMPILE))

  def test_scope_exclude_include_precedence(self):
    self.assertTrue(Scopes.RUNTIME.in_scope(include_scopes=Scopes.RUNTIME,
                                            exclude_scopes=Scopes.COMPILE))
    self.assertFalse(Scopes.RUNTIME.in_scope(include_scopes=Scopes.RUNTIME,
                                             exclude_scopes=Scopes.RUNTIME))

  def test_scope_equality(self):
    self.assertEquals(Scope('a b'), Scope('b') + Scope('a'))

  def test_invalid_in_scope_params(self):
    bad_values = ['', (), [], {}, set(), OrderedSet(), 'default', 'runtime', ('compile',)]
    for bad_value in bad_values:
      with self.assertRaises(ValueError):
        Scope('').in_scope(exclude_scopes=bad_value)
      with self.assertRaises(ValueError):
        Scope('').in_scope(include_scopes=bad_value)


class ScopedClosureTest(BaseTest):

  def assert_closure(self, expected_targets, roots, include_scopes=None, exclude_scopes=None,
                     respect_intransitive=True):
    self.assert_closure_dfs(expected_targets, roots, include_scopes, exclude_scopes,
                            respect_intransitive)
    self.assert_closure_bfs(expected_targets, roots, include_scopes, exclude_scopes,
                            respect_intransitive)
    self.assert_closure_dfs(expected_targets, roots, include_scopes, exclude_scopes,
                            respect_intransitive, postorder=True)

  def assert_closure_bfs(self, expected_targets, roots, include_scopes=None, exclude_scopes=None,
                     respect_intransitive=True, ordered=False):
    set_type = OrderedSet if ordered else set
    bfs_result = set_type(Target.closure_for_targets(
      target_roots=roots,
      include_scopes=include_scopes,
      exclude_scopes=exclude_scopes,
      respect_intransitive=respect_intransitive,
      bfs=True
    ))
    self.assertEquals(set_type(expected_targets), bfs_result)

  def assert_closure_dfs(self, expected_targets, roots, include_scopes=None, exclude_scopes=None,
                     respect_intransitive=True, ordered=False, postorder=None):
    set_type = OrderedSet if ordered else set
    result = set_type(Target.closure_for_targets(
      target_roots=roots,
      include_scopes=include_scopes,
      exclude_scopes=exclude_scopes,
      respect_intransitive=respect_intransitive,
      postorder=postorder
    ))
    self.assertEquals(set_type(expected_targets), result)

  def test_find_normal_dependencies(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[a])

    self.assert_closure({a, b, c, d}, {a, b, c, d})
    self.assert_closure({a, b, c, d}, {c, d})
    self.assert_closure({d, a}, {d})

  def test_intransitive(self):
    a = self.make_target('a')
    b_intransitive = self.make_target('b_intransitive', _transitive=False, dependencies=[a])
    c = self.make_target('c', dependencies=[b_intransitive])
    d = self.make_target('d', dependencies=[c])
    e = self.make_target('e', dependencies=[a])

    self.assert_closure({e, a}, {e})
    self.assert_closure({d, c}, {d})
    self.assert_closure({c, b_intransitive, a}, {c})
    self.assert_closure({b_intransitive, a}, {b_intransitive})
    self.assert_closure({e, d, a, c}, {e, d})
    self.assert_closure_dfs([d, c, b_intransitive, a], [d, c], ordered=True)
    self.assert_closure_dfs([c, d, a, b_intransitive], [d, c], ordered=True, postorder=True)
    self.assert_closure_bfs([d, c, b_intransitive, a], [d, c], ordered=True)
    self.assert_closure({a, b_intransitive, d, c}, {d}, respect_intransitive=False)

  def test_intransitive_diamond(self):
    a = self.make_target('a')
    b = self.make_target('b', _transitive=False, dependencies=[a])
    c = self.make_target('c', dependencies=[a])
    d = self.make_target('d', dependencies=[b, c])
    e = self.make_target('e', dependencies=[d])

    self.assert_closure({a, c, d, e}, {e})
    self.assert_closure({a, b, c, d, e}, {e}, respect_intransitive=False)

  def test_scope_include_exclude(self):
    a = self.make_target('a')
    b = self.make_target('b', scope=Scopes.RUNTIME, dependencies=[a])
    c = self.make_target('c', dependencies=[b])

    self.assert_closure({a, b, c}, {c}, include_scopes=Scopes.RUNTIME | Scopes.DEFAULT)
    self.assert_closure({c}, {c}, exclude_scopes=Scopes.RUNTIME)

  def test_scope_diamond(self):
    a = self.make_target('a')
    b = self.make_target('b', scope=Scopes.RUNTIME, dependencies=[a])
    b_alt = self.make_target('b_alt', dependencies=[a])
    c = self.make_target('c', dependencies=[b, b_alt])

    self.assert_closure({a, b, b_alt, c}, {c}, include_scopes=Scopes.RUNTIME | Scopes.DEFAULT)
    self.assert_closure({a, b_alt, c}, {c}, exclude_scopes=Scopes.RUNTIME)

  def test_include_root_level_unconditionally(self):
    a = self.make_target('a', scope=Scopes.COMPILE)
    a_root = self.make_target('a_root', scope=Scopes.COMPILE, dependencies=[a])
    b = self.make_target('b')
    b_root = self.make_target('b_root', scope=Scopes.RUNTIME, dependencies=[b])

    self.assert_closure({a_root, b_root}, {a_root, b_root}, include_scopes=Scopes.TEST)
    self.assert_closure({a_root, b_root, b}, {a_root, b_root}, include_scopes=Scopes.DEFAULT)
    self.assert_closure({a_root, b_root, a}, {a_root, b_root}, include_scopes=Scopes.COMPILE)
