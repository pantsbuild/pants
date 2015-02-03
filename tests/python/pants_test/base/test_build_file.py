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

  def setUp(self):
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
    BuildFileTest.touch('grandparent/parent/child5/BUILD')
    BuildFileTest.makedirs('path-that-does-exist')
    BuildFileTest.touch('path-that-does-exist/BUILD.invalid.suffix')
    self.buildfile = BuildFileTest.buildfile('grandparent/parent/BUILD')


  @classmethod
  def tearDownClass(cls):
    shutil.rmtree(BuildFileTest.root_dir)


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
        BuildFileTest.buildfile('grandparent/parent/child5'),
    ]), self.buildfile.descendants())

  def testMustExistFalse(self):
    buildfile = BuildFile(BuildFileTest.root_dir, "path-that-does-not-exist/BUILD", must_exist=False)
    self.assertEquals(OrderedSet([buildfile]), buildfile.family())

  def testMustExistTrue(self):
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(BuildFileTest.root_dir, "path-that-does-not-exist/BUILD", must_exist=True)
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(BuildFileTest.root_dir, "path-that-does-exist/BUILD", must_exist=True)
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(BuildFileTest.root_dir, "path-that-does-exist/BUILD.invalid.suffix", must_exist=True)

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

  def test_buildfile_with_dir_must_exist_false(self):
    # We should be able to create a BuildFile against a dir called BUILD if must_exist is false.
    # This is used in what_changed for example.
    buildfile = BuildFile(BuildFileTest.root_dir, 'grandparent/BUILD', must_exist=False)
    self.assertFalse(buildfile.exists())

  def test_buildfile_with_dir_must_exist_true(self):
    # We should NOT be able to create a BuildFile instance against a dir called BUILD
    # in the default case.
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(BuildFileTest.root_dir, 'grandparent/BUILD')

  def test_directory_called_build_skipped(self):
    # Ensure the buildfiles found do not include grandparent/BUILD since it is a dir.
    buildfiles = BuildFile.scan_buildfiles(os.path.join(BuildFileTest.root_dir, 'grandparent'))

    self.assertEquals(OrderedSet([
      BuildFileTest.buildfile('grandparent/parent/BUILD'),
      BuildFileTest.buildfile('grandparent/parent/BUILD.twitter'),
      BuildFileTest.buildfile('grandparent/parent/child1/BUILD'),
      BuildFileTest.buildfile('grandparent/parent/child1/BUILD.twitter'),
      BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD'),
      BuildFileTest.buildfile('grandparent/parent/child5/BUILD'),

      ]), buildfiles)

    def test_scan_buildfiles_exclude(self):
      buildfiles = BuildFile.scan_buildfiles(
        BuildFileTest.root_dir, '', spec_excludes=[
          os.path.join(BuildFileTest.root_dir, 'grandparent/parent/child1'),
          os.path.join(BuildFileTest.root_dir, 'grandparent/parent/child2')
        ])

      self.assertEquals([BuildFileTest.buildfile('BUILD'),
                         BuildFileTest.buildfile('/BUILD.twitter'),
                         BuildFileTest.buildfile('/grandparent/parent/BUILD'),
                         BuildFileTest.buildfile('/grandparent/parent/BUILD.twitter'),
                         BuildFileTest.buildfile('/grandparent/parent/child5/BUILD'),
                         ],
                        buildfiles)

  def test_invalid_root_dir_error(self):
    BuildFileTest.touch('BUILD')
    with self.assertRaises(BuildFile.InvalidRootDirError):
      BuildFile('tmp', 'grandparent/BUILD')

  def test_exception_class_hierarchy(self):
    """Exception handling code depends on the fact that all exceptions from BuildFile are
    subclassed from the BuildFileError base class.
    """
    self.assertIsInstance(BuildFile.InvalidRootDirError(), BuildFile.BuildFileError)
    self.assertIsInstance(BuildFile.MissingBuildFileError(), BuildFile.BuildFileError)
