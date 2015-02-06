# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_graph import BuildGraph
from pants.base.target import Target
from pants_test.base_test import BaseTest


# TODO(Eric Ayers) There are many untested methods in BuildGraph left to be tested.

class BuildGraphTest(BaseTest):
  def test_target_invalid(self):
    self.add_to_build_file('a/BUILD', 'target(name="a")')
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(SyntheticAddress.parse('a:nope'))

    self.add_to_build_file('b/BUILD', 'target(name="a")')
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(SyntheticAddress.parse('b'))
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(SyntheticAddress.parse('b:b'))

  def test_transitive_closure_address(self):
    self.add_to_build_file('BUILD', dedent('''
        target(name='foo',
               dependencies=[
                 'a',
               ])
      '''))

    self.add_to_build_file('a/BUILD', dedent('''
        target(name='a',
               dependencies=[
                 'a/b:bat',
               ])
      '''))

    self.add_to_build_file('a/b/BUILD', dedent('''
        target(name='bat')
      '''))

    root_address = SyntheticAddress.parse('//:foo')
    self.build_graph.inject_address_closure(root_address)
    self.assertEqual(len(self.build_graph.transitive_subgraph_of_addresses([root_address])), 3)

  def test_no_targets(self):
    self.add_to_build_file('empty/BUILD', 'pass')
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(SyntheticAddress.parse('empty'))
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(SyntheticAddress.parse('empty:foo'))

  def test_contains_address(self):
    a = SyntheticAddress.parse('a')
    self.assertFalse(self.build_graph.contains_address(a))
    target = Target(name='a',
                    address=a,
                    build_graph=self.build_graph)
    self.build_graph.inject_target(target)
    self.assertTrue(self.build_graph.contains_address(a))

  def test_get_target_from_spec(self):
    a = self.make_target('foo:a')
    result = self.build_graph.get_target_from_spec('foo:a')
    self.assertEquals(a, result)
    b = self.make_target('foo:b')
    result = self.build_graph.get_target_from_spec(':b', relative_to='foo')
    self.assertEquals(b, result)

  def test_walk_graph(self):
    # Make sure that BuildGraph.walk_transitive_dependency_graph() and
    # BuildGraph.walk_transitive_dependee_graph() return DFS preorder (or postorder) traversal.
    def assertDependencyWalk(target, results, postorder=False):
      targets = []
      self.build_graph.walk_transitive_dependency_graph([target.address],
                                                         lambda x: targets.append(x),
                                                        postorder=postorder)
      self.assertEquals(results, targets)

    def assertDependeeWalk(target, results, postorder=False):
      targets = []
      self.build_graph.walk_transitive_dependee_graph([target.address],
                                                        lambda x: targets.append(x),
                                                        postorder=postorder)
      self.assertEquals(results, targets)

    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    e = self.make_target('e', dependencies=[d])

    assertDependencyWalk(a, [a])
    assertDependencyWalk(b, [b, a])
    assertDependencyWalk(c, [c, b, a])
    assertDependencyWalk(d, [d, c, b, a])
    assertDependencyWalk(e, [e, d, c, b, a])

    assertDependeeWalk(a, [a, b, c, d, e])
    assertDependeeWalk(b, [b, c, d, e])
    assertDependeeWalk(c, [c, d, e])
    assertDependeeWalk(d, [d, e])
    assertDependeeWalk(e, [e])

    assertDependencyWalk(a, [a], postorder=True)
    assertDependencyWalk(b, [a, b], postorder=True)
    assertDependencyWalk(c, [a, b, c], postorder=True)
    assertDependencyWalk(d, [a, b, c, d], postorder=True)
    assertDependencyWalk(e, [a, b, c, d, e], postorder=True)

    assertDependeeWalk(a, [e, d, c, b, a], postorder=True)
    assertDependeeWalk(b, [e, d, c, b], postorder=True)
    assertDependeeWalk(c, [e, d, c], postorder=True)
    assertDependeeWalk(d, [e, d], postorder=True)
    assertDependeeWalk(e, [e], postorder=True)

    # Try a case where postorder traversal is not identical to reversed preorder traversal
    c = self.make_target('c1', dependencies=[])
    d = self.make_target('d1', dependencies=[c])
    b = self.make_target('b1', dependencies=[c, d])
    e = self.make_target('e1', dependencies=[b])
    a = self.make_target('a1', dependencies=[b, e])

    assertDependencyWalk(a, [a, b, c, d, e])
    assertDependencyWalk(a, [c, d, b, e, a], postorder=True)

  def test_target_closure(self):
    a = self.make_target('a')
    self.assertEquals([a], a.closure())
    b = self.make_target('b', dependencies=[a])
    self.assertEquals([b, a], b.closure())
    c = self.make_target('c', dependencies=[b])
    self.assertEquals([c, b, a], c.closure())
    d = self.make_target('d', dependencies=[a, c])
    self.assertEquals([d, a, c, b], d.closure())

  def test_target_walk(self):
    def assertWalk(expected, target):
      results = []
      target.walk(lambda x: results.append(x))
      self.assertEquals(expected, results)

    a = self.make_target('a')
    assertWalk([a], a)
    b = self.make_target('b', dependencies=[a])
    assertWalk([b, a], b)
    c = self.make_target('c', dependencies=[b])
    assertWalk([c, b, a], c)
    d = self.make_target('d', dependencies=[a, c])
    assertWalk([d, a, c, b], d)

  def test_lookup_exception(self):
    # There is code that depends on the fact that TransitiveLookupError is a subclass of
    # AddressLookupError
    self.assertIsInstance(BuildGraph.TransitiveLookupError(), AddressLookupError)

  def inject_address_closure(self, spec):
    self.build_graph.inject_address_closure(SyntheticAddress.parse(spec))

  def test_invalid_address(self):

    with self.assertRaisesRegexp(AddressLookupError,
                                 '^BUILD file does not exist at:.*/BUILD'):
      self.inject_address_closure('//:a')

    self.add_to_build_file('BUILD',
                           'target(name="a", '
                           '  dependencies=["non-existent-path:b"],'
                           ')')
    with self.assertRaisesRegexp(BuildGraph.TransitiveLookupError,
                                 '^BUILD file does not exist at:.*/non-existent-path/BUILD'
                                 '\s+when translating spec non-existent-path:b'
                                 '\s+referenced from :a$'):
      self.inject_address_closure('//:a')

  def test_invalid_address_two_hops(self):
    self.add_to_build_file('BUILD',
                           'target(name="a", '
                           '  dependencies=["goodpath:b"],'
                           ')')
    self.add_to_build_file('goodpath/BUILD',
                           'target(name="b", '
                           '  dependencies=["non-existent-path:c"],'
                           ')')
    with self.assertRaisesRegexp(BuildGraph.TransitiveLookupError,
                                 '^BUILD file does not exist at: .*/non-existent-path/BUILD'
                                 '\s+when translating spec non-existent-path:c'
                                 '\s+referenced from goodpath:b'
                                 '\s+referenced from :a$'):
      self.inject_address_closure('//:a')

  def test_invalid_address_two_hops_same_file(self):
    self.add_to_build_file('BUILD',
                           'target(name="a", '
                           '  dependencies=["goodpath:b"],'
                           ')')
    self.add_to_build_file('goodpath/BUILD',
                           'target(name="b", '
                           '  dependencies=[":c"],'
                           ')\n'
                           'target(name="c", '
                           '  dependencies=["non-existent-path:d"],'
                           ')')
    with self.assertRaisesRegexp(BuildGraph.TransitiveLookupError,
                                 '^BUILD file does not exist at:.*/non-existent-path/BUILD'
                                 '\s+when translating spec non-existent-path:d'
                                 '\s+referenced from goodpath:c'
                                 '\s+referenced from goodpath:b'
                                 '\s+referenced from :a$'):
      self.inject_address_closure('//:a')

  def test_raise_on_duplicate_dependencies(self):
    self.add_to_build_file('BUILD',
                           'target(name="a", '
                           '  dependencies=['
                           '    "other:b",'
                           '    "//other:b",'  # we should perform the test on normalized addresses
                           '])')
    self.add_to_build_file('other/BUILD',
                           'target(name="b")')

    with self.assertRaisesRegexp(
        BuildGraph.TransitiveLookupError,
        '^Addresses in dependencies must be unique. \'other:b\' is referenced more than once.'
        '\s+referenced from :a$'):
      self.inject_address_closure('//:a')
