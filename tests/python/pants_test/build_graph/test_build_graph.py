# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.build_graph.address import Address, parse_spec
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest


# TODO(Eric Ayers) There are many untested methods in BuildGraph left to be tested.
class BuildGraphTest(BaseTest):

  def inject_graph(self, root_spec, graph_dict):
    """Given a root spec, injects relevant targets from the graph represented by graph_dict.

    graph_dict should contain address specs, keyed by sources with lists of value destinations.
    Each created target will be a simple `target` alias.

    Returns the parsed Address for the root_spec.
    """
    for src, targets in graph_dict.items():
      src_path, src_name = parse_spec(src)
      if not src_path:
        # The target is located in the root.
        src_path = '.'
      self.add_to_build_file(
          '{}/BUILD'.format(src_path),
          '''target(name='{}', dependencies=[{}])\n'''.format(
            src_name,
            "'{}'".format("','".join(targets)) if targets else ''
          )
      )
    root_address = Address.parse(root_spec)
    self.build_graph.inject_address_closure(root_address)
    return root_address

  def test_target_invalid(self):
    self.add_to_build_file('a/BUILD', 'target(name="a")')
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(Address.parse('a:nope'))

    self.add_to_build_file('b/BUILD', 'target(name="a")')
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(Address.parse('b'))
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(Address.parse('b:b'))

  def test_transitive_closure_address(self):
    root_address = self.inject_graph('//:foo', {
      "//:foo": ['a'],
      "a": ['a/b:bat'],
      "a/b:bat": [],
    })

    self.assertEqual(len(self.build_graph.transitive_subgraph_of_addresses([root_address])), 3)

  def test_no_targets(self):
    self.add_to_build_file('empty/BUILD', 'pass')
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(Address.parse('empty'))
    with self.assertRaises(AddressLookupError):
      self.build_graph.inject_address_closure(Address.parse('empty:foo'))

  def test_contains_address(self):
    a = Address.parse('a')
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

  def test_closure(self):
    self.assertEquals([], BuildGraph.closure([]))
    a = self.make_target('a')
    self.assertEquals([a], BuildGraph.closure([a]))
    b = self.make_target('b', dependencies=[a])
    self.assertEquals([b, a], BuildGraph.closure([b]))
    c = self.make_target('c', dependencies=[b])
    self.assertEquals([c, b, a], BuildGraph.closure([c]))
    d = self.make_target('d', dependencies=[a, c])
    self.assertEquals([d, a, c, b], BuildGraph.closure([d]))

    def d_gen():
      yield d
    self.assertEquals([d, a, c, b], BuildGraph.closure(d_gen()))

    def empty_gen():
      return
      yield
    self.assertEquals([], BuildGraph.closure(empty_gen()))

  def test_closure_bfs(self):
    root = self.inject_graph('a', {
      'a': ['b', 'c'],
      'b': ['d', 'e'],
      'c': ['f', 'g'],
      'd': ['h', 'i'],
      'e': ['j', 'k'],
      'f': ['l', 'm'],
      'g': ['n', 'o'],
      'h': [], 'i': [], 'j': [], 'k': [], 'l': [], 'm': [], 'n': [], 'o': [],
    })

    bfs_closure = BuildGraph.closure([self.build_graph.get_target(root)], bfs=True)
    self.assertEquals(
        [t.address.target_name for t in bfs_closure],
        [str(six.unichr(x)) for x in six.moves.xrange(ord('a'), ord('o') + 1)],
    )

  def test_transitive_subgraph_of_addresses_bfs(self):
    root = self.inject_graph('a', {
      'a': ['b', 'c'],
      'b': ['d', 'e'],
      'c': ['f', 'g'],
      'd': ['h', 'i'],
      'e': ['j', 'k'],
      'f': ['l', 'm'],
      'g': ['n', 'o'],
      'h': [], 'i': [], 'j': [], 'k': [], 'l': [], 'm': [], 'n': [], 'o': [],
    })

    self.assertEquals(
        [t.address.target_name for t in self.build_graph.transitive_subgraph_of_addresses_bfs([root])],
        [str(six.unichr(x)) for x in six.moves.xrange(ord('a'), ord('o') + 1)],
    )

  def test_transitive_subgraph_of_addresses_bfs_predicate(self):
    root = self.inject_graph('a', {
      'a': ['b', 'c'],
      'b': ['d', 'e'],
      'c': [], 'd': [], 'e': [],
    })

    predicate = lambda t: t.address.target_name != 'b'
    filtered = self.build_graph.transitive_subgraph_of_addresses_bfs([root], predicate=predicate)

    self.assertEquals([t.address.target_name for t in filtered], ['a', 'c'])

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
    self.build_graph.inject_address_closure(Address.parse(spec))

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
