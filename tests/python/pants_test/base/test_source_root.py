# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest2 as unittest

from twitter.common.collections import OrderedSet

from pants.base.address import parse_spec, SyntheticAddress
from pants.base.addressable import AddressableCallProxy
from pants.base.exceptions import TargetDefinitionException
from pants.base.source_root import SourceRoot, SourceRootTree
from pants.base.target import Target


class TestTarget(Target):
  def __init__(self, spec):
    spec_path, target_name = parse_spec(spec)
    super(TestTarget, self).__init__(target_name, SyntheticAddress.parse(spec), None)


class NotTestTarget(Target):
  def __init__(self, spec):
    spec_path, target_name = parse_spec(spec)
    super(NotTestTarget, self).__init__(target_name, SyntheticAddress.parse(spec), None)


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

  def test_reset(self):
    self._assert_source_root_empty()
    SourceRoot.register("tests", TestTarget)
    self.assertEquals({"tests": OrderedSet([TestTarget])}, SourceRoot.all_roots())

    SourceRoot.reset()

    self._assert_source_root_empty()

  def test_here(self):

    class MockParseContext(object):
      def __init__(self):
        self.rel_path = "mock/foo"
    target = TestTarget("//mock/foo/bar:baz")
    proxy = AddressableCallProxy(addressable_type=target.get_addressable_type(),
                                 build_file=None,
                                 registration_callback=None)
    self.assertEqual("mock/foo/bar", SourceRoot.find(target))
    SourceRoot(MockParseContext()).here(proxy)
    self.assertEqual("mock/foo", SourceRoot.find(target))

  def test_find(self):
    # When no source_root is registered, it should just return the path from the address
    self.assertEqual("tests/foo/bar", SourceRoot.find(TestTarget("//tests/foo/bar:baz")))
    SourceRoot.register("tests/foo", TestTarget)
    # After the source root is registered, you should get the source root
    self.assertEquals("tests/foo", SourceRoot.find(TestTarget("//tests/foo/bar:baz")))
    with self.assertRaises(TargetDefinitionException):
      SourceRoot.find(NotTestTarget("//tests/foo/foobar:qux"))

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
    self.assertEquals(("tests/language", set([NotTestTarget, TestTarget])),
                      tree.get_root_and_types("tests/language/foo"),
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
