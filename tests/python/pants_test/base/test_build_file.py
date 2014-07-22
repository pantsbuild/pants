# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil
import tempfile
import unittest

from twitter.common.collections import OrderedSet

from pants.base.build_file import BuildFile
from pants.util.dirutil import safe_mkdir, touch


class BuildFileTest(unittest.TestCase):

  @classmethod
  def makedirs(cls, path):
    safe_mkdir(os.path.join(BuildFileTest.root_dir, path))

  @classmethod
  def touch(cls, path):
    touch(os.path.join(BuildFileTest.root_dir, path))

  @classmethod
  def buildfile(cls, path):
    return BuildFile(BuildFileTest.root_dir, path)

  @classmethod
  def setUpClass(cls):
    BuildFileTest.base_dir = tempfile.mkdtemp()

    # Seed a BUILD outside the build root that should not be detected
    touch(os.path.join(BuildFileTest.base_dir, 'BUILD'))

    BuildFileTest.root_dir = os.path.join(BuildFileTest.base_dir, 'root')

    BuildFileTest.touch('grandparent/parent/BUILD')
    BuildFileTest.touch('grandparent/parent/BUILD.twitter')
    # Tricky!  This is a directory
    BuildFileTest.makedirs('grandparent/parent/BUILD.dir')
    BuildFileTest.makedirs('grandparent/BUILD')
    BuildFileTest.touch('BUILD')
    BuildFileTest.touch('BUILD.twitter')
    BuildFileTest.touch('grandparent/parent/child1/BUILD')
    BuildFileTest.touch('grandparent/parent/child1/BUILD.twitter')
    BuildFileTest.touch('grandparent/parent/child2/child3/BUILD')
    BuildFileTest.makedirs('grandparent/parent/child2/BUILD')
    BuildFileTest.makedirs('grandparent/parent/child4')

  @classmethod
  def tearDownClass(cls):
    shutil.rmtree(BuildFileTest.root_dir)

  def setUp(self):
    self.buildfile = BuildFileTest.buildfile('grandparent/parent/BUILD')

  def testSiblings(self):
    buildfile = BuildFileTest.buildfile('grandparent/parent/BUILD.twitter')
    self.assertEquals(OrderedSet([buildfile]), OrderedSet(self.buildfile.siblings()))
    self.assertEquals(OrderedSet([self.buildfile]), OrderedSet(buildfile.siblings()))

    buildfile = BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet(), OrderedSet(buildfile.siblings()))

  def testFamily(self):
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('grandparent/parent/BUILD'),
        BuildFileTest.buildfile('grandparent/parent/BUILD.twitter'),
    ]), self.buildfile.family())

    buildfile = BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet([buildfile]), buildfile.family())

  def testAncestors(self):
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('BUILD'),
        BuildFileTest.buildfile('BUILD.twitter'),
    ]), self.buildfile.ancestors())

  def testDescendants(self):
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('grandparent/parent/child1/BUILD'),
        BuildFileTest.buildfile('grandparent/parent/child1/BUILD.twitter'),
        BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD'),
    ]), self.buildfile.descendants())

  def testMustExistFalse(self):
    buildfile = BuildFile(BuildFileTest.root_dir, "path-that-does-not-exist/BUILD", must_exist=False)
    self.assertEquals(OrderedSet([buildfile]), buildfile.family())

  def testSuffixOnly(self):
    BuildFileTest.makedirs('suffix-test')
    BuildFileTest.touch('suffix-test/BUILD.suffix')
    BuildFileTest.touch('suffix-test/BUILD.suffix2')
    BuildFileTest.makedirs('suffix-test/child')
    BuildFileTest.touch('suffix-test/child/BUILD.suffix3')
    buildfile = BuildFileTest.buildfile('suffix-test/BUILD.suffix')
    self.assertEquals(OrderedSet([BuildFileTest.buildfile('suffix-test/BUILD.suffix2')]),
        OrderedSet(buildfile.siblings()))
    self.assertEquals(OrderedSet([BuildFileTest.buildfile('suffix-test/BUILD.suffix'),
        BuildFileTest.buildfile('suffix-test/BUILD.suffix2')]),
        buildfile.family())
    self.assertEquals(OrderedSet([BuildFileTest.buildfile('suffix-test/child/BUILD.suffix3')]),
        buildfile.descendants())

  def testAncestorsSuffix1(self):
    BuildFileTest.makedirs('suffix-test1/parent')
    BuildFileTest.touch('suffix-test1/parent/BUILD.suffix')
    BuildFileTest.touch('suffix-test1/BUILD')
    buildfile = BuildFileTest.buildfile('suffix-test1/parent/BUILD.suffix')
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('suffix-test1/BUILD'),
        BuildFileTest.buildfile('BUILD'),
        BuildFileTest.buildfile('BUILD.twitter')]),
        buildfile.ancestors())

  def testAncestorsSuffix2(self):
    BuildFileTest.makedirs('suffix-test2')
    BuildFileTest.makedirs('suffix-test2/subdir')
    BuildFileTest.touch('suffix-test2/subdir/BUILD.foo')
    BuildFileTest.touch('suffix-test2/BUILD.bar')
    buildfile = BuildFileTest.buildfile('suffix-test2/subdir/BUILD.foo')
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('suffix-test2/BUILD.bar'),
        BuildFileTest.buildfile('BUILD'),
        BuildFileTest.buildfile('BUILD.twitter')]),
        buildfile.ancestors())
