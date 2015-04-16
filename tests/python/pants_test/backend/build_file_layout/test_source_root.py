# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from twitter.common.collections import OrderedSet

from pants.backend.build_file_layout.source_root import SourceRoot, SourceRootTree
from pants.base.address import SyntheticAddress, parse_spec
from pants.base.addressable import AddressableCallProxy
from pants.base.exceptions import TargetDefinitionException
from pants.base.target import Target


class TestTarget(Target):
  def __init__(self, spec):
    spec_path, target_name = parse_spec(spec)
    super(TestTarget, self).__init__(target_name, SyntheticAddress.parse(spec), None)


class NotTestTarget(Target):
  def __init__(self, spec):
    spec_path, target_name = parse_spec(spec)
    super(NotTestTarget, self).__init__(target_name, SyntheticAddress.parse(spec), None)


class AnotherTarget(Target):
  def __init__(self, spec):
    spec_path, target_name = parse_spec(spec)
    super(AnotherTarget, self).__init__(target_name, SyntheticAddress.parse(spec), None)


class SourceRootTest(unittest.TestCase):
  """Tests for SourceRoot.  SourceRoot is a singleton so we must make sure this
  test cleans up after itself.
  """

  def tearDown(self):
    SourceRoot.reset()

  def _assert_source_root_empty(self):
    self.assertEqual({}, SourceRoot.all_roots())
    with self.assertRaises(KeyError):
      self.assertEqual(set(), SourceRoot.types("tests"))
    with self.assertRaises(KeyError):
      self.assertEqual(set(), SourceRoot.roots(TestTarget))

  def test_register(self):
    self._assert_source_root_empty()

    SourceRoot.register("tests", TestTarget)

    self.assertEquals({"tests": OrderedSet([TestTarget])}, SourceRoot.all_roots())
    self.assertEquals(OrderedSet([TestTarget]), SourceRoot.types("tests"))
    self.assertEquals(OrderedSet(["tests"]), SourceRoot.roots(TestTarget))

  def test_register_none(self):
    self._assert_source_root_empty()

    SourceRoot.register("tests", )
    self.assertEquals({"tests": OrderedSet()}, SourceRoot.all_roots())
    self.assertEquals(OrderedSet(), SourceRoot.types("tests"))
    self.assertEquals("tests", SourceRoot.find(TestTarget("//tests/foo/bar:baz")))
    self.assertEquals("tests", SourceRoot.find_by_path("tests/foo/bar"))

  def test_reset(self):
    self._assert_source_root_empty()
    SourceRoot.register("tests", TestTarget)
    self.assertEquals({"tests": OrderedSet([TestTarget])}, SourceRoot.all_roots())

    SourceRoot.reset()

    self._assert_source_root_empty()

  def test_here(self):
    target = TestTarget("//mock/foo/bar:baz")
    proxy = AddressableCallProxy(addressable_type=target.get_addressable_type(),
                                 build_file=None,
                                 registration_callback=None)
    self.assertEqual("mock/foo/bar", SourceRoot.find(target))
    SourceRoot("mock/foo").here(proxy)
    self.assertEqual("mock/foo", SourceRoot.find(target))

  def test_find(self):
    # When no source_root is registered, it should just return the path from the address
    self.assertEqual("tests/foo/bar", SourceRoot.find(TestTarget("//tests/foo/bar:baz")))
    SourceRoot.register("tests/foo", TestTarget)
    # After the source root is registered, you should get the source root
    self.assertEquals("tests/foo", SourceRoot.find(TestTarget("//tests/foo/bar:baz")))
    with self.assertRaises(TargetDefinitionException):
      SourceRoot.find(NotTestTarget("//tests/foo/foobar:qux"))

  def test_find_by_path(self):
    # No source_root is registered yet
    query = "tests/foo/bar:baz"
    self.assertIsNone(SourceRoot.find_by_path(query),
                      msg="Query {query} Failed for tree: {dump}"
                      .format(query=query, dump=SourceRoot._dump()))
    SourceRoot.register("tests/foo", TestTarget)
    self.assertEquals("tests/foo", SourceRoot.find_by_path(query),
                      msg="Query {query} Failed for tree: {dump}"
                      .format(query=query, dump=SourceRoot._dump()))
    self.assertIsNone(SourceRoot.find_by_path("tests/bar/foobar:qux"),
                                              msg="Failed for tree: {dump}"
                                              .format(dump=SourceRoot._dump()))

  def test_source_root_tree_node(self):
    root = SourceRootTree.Node("ROOT")
    self.assertIsNone(root.get("child1"))
    self.assertIsNone(root.get("child2"))
    child = root.get_or_add("child1")
    self.assertIsNotNone(child)
    self.assertEquals(child, root.get("child1"))
    self.assertIsNone(root.get("child2"))
    grandchild = child.get_or_add("grandchild")
    self.assertIsNone(root.get("grandchild"))
    self.assertEquals(grandchild, child.get("grandchild"))
    # Retrieve the same object on re-insertion
    self.assertEquals(grandchild, child.get_or_add("grandchild"))

  def test_source_root_tree(self):
    tree = SourceRootTree()
    self.assertEquals((None, None), tree.get_root_and_types(""))
    self.assertEquals((None, None), tree.get_root_and_types("tests/language"))
    self.assertEquals((None, None), tree.get_root_and_types("tests/language/foo"))
    self.assertEquals((None, None), tree.get_root_and_types("src/language"))
    self.assertEquals((None, None), tree.get_root_and_types("src"))

    tree.add_root("tests/language", set([NotTestTarget, TestTarget]))
    self.assertEquals(("tests/language", OrderedSet([NotTestTarget, TestTarget])),
                      tree.get_root_and_types("tests/language"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    root, types = tree.get_root_and_types("tests/language/foo")
    self.assertEquals("tests/language", root,
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals(set(types),
                      set([NotTestTarget, TestTarget]),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals((None, None), tree.get_root_and_types("src"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals((None, None), tree.get_root_and_types("src/bar"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals((None, None), tree.get_root_and_types("s"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))

    tree.add_root("src/language", set([NotTestTarget]))
    self.assertEquals(("tests/language", OrderedSet([NotTestTarget, TestTarget])),
                      tree.get_root_and_types("tests/language"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals(("tests/language", OrderedSet([NotTestTarget, TestTarget])),
                       tree.get_root_and_types("tests/language/foo"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals(("src/language", OrderedSet([NotTestTarget])),
                      tree.get_root_and_types("src/language"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals(("src/language", OrderedSet([NotTestTarget])),
                      tree.get_root_and_types("src/language/bar"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    self.assertEquals((None, None), tree.get_root_and_types("src"),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))
    with self.assertRaises(SourceRootTree.DuplicateSourceRootError):
      tree.add_root("tests/language", set([NotTestTarget]))
    with self.assertRaises(SourceRootTree.NestedSourceRootError):
      tree.add_root("tests", set([NotTestTarget]))

  def test_mutable(self):
    tree = SourceRootTree()
    tree.add_root("mutable/foo", set([NotTestTarget, TestTarget]), mutable=True)
    tree.add_root("immutable/foo", set([NotTestTarget, TestTarget]), mutable=False)
    with self.assertRaises(SourceRootTree.DuplicateSourceRootError):
      # Can't add an immutable root to a mutable root
      tree.add_root("mutable/foo", set([AnotherTarget]))
    with self.assertRaises(SourceRootTree.DuplicateSourceRootError):
      # Can't add an mutable root to an immutable root
      tree.add_root("immutable/foo", set([AnotherTarget]), mutable=True)
    # But can add a mutable root to a mutable root
    tree.add_root("mutable/foo", set([AnotherTarget]), mutable=True)
    self.assertEquals(set([AnotherTarget, NotTestTarget, TestTarget]),
                      set(tree.get_root_and_types("mutable/foo")[1]),
                      msg="Failed for tree: {dump}".format(dump=tree._dump()))

  def _add_siblings1(self, tree, common_root):
    tree.add_root(os.path.join(common_root, 'src/java'),[NotTestTarget])
    tree.add_root(os.path.join(common_root, 'src/resources'), [NotTestTarget])
    tree.add_root(os.path.join(common_root, 'tests/java'), [NotTestTarget, TestTarget])
    tree.add_root(os.path.join(common_root, 'tests/resources'), [NotTestTarget])

  def test_get_root_siblings(self):
    tree = SourceRootTree()

    self._add_siblings1(tree, "")
    self.assertEquals([], tree.get_root_siblings("foo/bar/baz"))
    self.assertEquals([], tree.get_root_siblings("src"))
    self.assertEquals(["src/java", "src/resources"],
                      tree.get_root_siblings("src/java"))
    self.assertEquals(["src/java", "src/resources"],
                      tree.get_root_siblings("src/resources"))
    self.assertEquals(["src/java", "src/resources"],
                      tree.get_root_siblings("src/java/org/pantsbuild/foo"))
    self.assertEquals(["src/java", "src/resources"],
                      tree.get_root_siblings("src/resources/org/pantsbuild/foo"))
    self.assertEquals([], tree.get_root_siblings("src/foo/bar/baz"))
    self.assertEquals(["tests/java", "tests/resources"],
                      tree.get_root_siblings("tests/java/org/pantsbuild/foo"))
    self.assertEquals(["tests/java", "tests/resources"],
                      tree.get_root_siblings("tests/resources/org/pantsbuild/foo"))
    self.assertEquals([], tree.get_root_siblings("tests/foo/bar/baz"))

    self._add_siblings1(tree, "examples")
    self.assertEquals([], tree.get_root_siblings("foo/bar/baz"))
    self.assertEquals(["src/java", "src/resources"],
                      tree.get_root_siblings("src/java/org/pantsbuild/foo"))
    self.assertEquals(["tests/java", "tests/resources"],
                      tree.get_root_siblings("tests/resources/org/pantsbuild/foo"))
    self.assertEquals(["examples/src/java", "examples/src/resources"],
                      tree.get_root_siblings("examples/src/java/org/pantsbuild/foo"))
    self.assertEquals(["examples/tests/java", "examples/tests/resources"],
                      tree.get_root_siblings("examples/tests/resources/org/pantsbuild/foo"))
