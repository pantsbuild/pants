# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
import unittest

from twitter.common.collections import OrderedSet
from twitter.common.lang import Compatibility

from pants.base.build_file import BuildFile
from pants.util.dirutil import safe_mkdir, safe_open, touch


class BuildFileTest(unittest.TestCase):

  def fullpath(self, path):
    return os.path.join(self.root_dir, path)

  def makedirs(self, path):
    safe_mkdir(self.fullpath(path))

  def touch(self, path):
    touch(self.fullpath(path))

  def create_buildfile(self, path):
    return BuildFile(self.root_dir, path)

  def setUp(self):
    self.base_dir = tempfile.mkdtemp()

    # Seed a BUILD outside the build root that should not be detected
    touch(os.path.join(self.base_dir, 'BUILD'))

    self.root_dir = os.path.join(self.base_dir, 'root')

    self.touch('grandparent/parent/BUILD')
    self.touch('grandparent/parent/BUILD.twitter')
    # Tricky!  This is a directory
    self.makedirs('grandparent/parent/BUILD.dir')
    self.makedirs('grandparent/BUILD')
    self.touch('BUILD')
    self.touch('BUILD.twitter')
    self.touch('grandparent/parent/child1/BUILD')
    self.touch('grandparent/parent/child1/BUILD.twitter')
    self.touch('grandparent/parent/child2/child3/BUILD')
    self.makedirs('grandparent/parent/child2/BUILD')
    self.makedirs('grandparent/parent/child4')
    self.touch('grandparent/parent/child5/BUILD')
    self.makedirs('path-that-does-exist')
    self.touch('path-that-does-exist/BUILD.invalid.suffix')
    self.buildfile = self.create_buildfile('grandparent/parent/BUILD')

  def tearDown(self):
    shutil.rmtree(self.base_dir)

  def testSiblings(self):
    buildfile = self.create_buildfile('grandparent/parent/BUILD.twitter')
    self.assertEquals(OrderedSet([buildfile]), OrderedSet(self.buildfile.siblings()))
    self.assertEquals(OrderedSet([self.buildfile]), OrderedSet(buildfile.siblings()))

    buildfile = self.create_buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet(), OrderedSet(buildfile.siblings()))

  def testFamily(self):
    self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
    ]), self.buildfile.family())

    buildfile = self.create_buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet([buildfile]), buildfile.family())

  def testAncestors(self):
    self.assertEquals(OrderedSet([
        self.create_buildfile('BUILD'),
        self.create_buildfile('BUILD.twitter'),
    ]), self.buildfile.ancestors())

  def testDescendants(self):
    self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/child1/BUILD'),
        self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
        self.create_buildfile('grandparent/parent/child5'),
    ]), self.buildfile.descendants())

  def testMustExistFalse(self):
    buildfile = BuildFile(self.root_dir, "path-that-does-not-exist/BUILD", must_exist=False)
    self.assertEquals(OrderedSet([buildfile]), buildfile.family())

  def testMustExistTrue(self):
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(self.root_dir, "path-that-does-not-exist/BUILD", must_exist=True)
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(self.root_dir, "path-that-does-exist/BUILD", must_exist=True)
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(self.root_dir, "path-that-does-exist/BUILD.invalid.suffix", must_exist=True)

  def testSuffixOnly(self):
    self.makedirs('suffix-test')
    self.touch('suffix-test/BUILD.suffix')
    self.touch('suffix-test/BUILD.suffix2')
    self.makedirs('suffix-test/child')
    self.touch('suffix-test/child/BUILD.suffix3')
    buildfile = self.create_buildfile('suffix-test/BUILD.suffix')
    self.assertEquals(OrderedSet([self.create_buildfile('suffix-test/BUILD.suffix2')]),
        OrderedSet(buildfile.siblings()))
    self.assertEquals(OrderedSet([self.create_buildfile('suffix-test/BUILD.suffix'),
        self.create_buildfile('suffix-test/BUILD.suffix2')]),
        buildfile.family())
    self.assertEquals(OrderedSet([self.create_buildfile('suffix-test/child/BUILD.suffix3')]),
        buildfile.descendants())

  def testAncestorsSuffix1(self):
    self.makedirs('suffix-test1/parent')
    self.touch('suffix-test1/parent/BUILD.suffix')
    self.touch('suffix-test1/BUILD')
    buildfile = self.create_buildfile('suffix-test1/parent/BUILD.suffix')
    self.assertEquals(OrderedSet([
        self.create_buildfile('suffix-test1/BUILD'),
        self.create_buildfile('BUILD'),
        self.create_buildfile('BUILD.twitter')]),
        buildfile.ancestors())

  def testAncestorsSuffix2(self):
    self.makedirs('suffix-test2')
    self.makedirs('suffix-test2/subdir')
    self.touch('suffix-test2/subdir/BUILD.foo')
    self.touch('suffix-test2/BUILD.bar')
    buildfile = self.create_buildfile('suffix-test2/subdir/BUILD.foo')
    self.assertEquals(OrderedSet([
        self.create_buildfile('suffix-test2/BUILD.bar'),
        self.create_buildfile('BUILD'),
        self.create_buildfile('BUILD.twitter')]),
        buildfile.ancestors())

  def test_buildfile_with_dir_must_exist_false(self):
    # We should be able to create a BuildFile against a dir called BUILD if must_exist is false.
    # This is used in what_changed for example.
    buildfile = BuildFile(self.root_dir, 'grandparent/BUILD', must_exist=False)
    self.assertFalse(buildfile.exists())

  def test_buildfile_with_dir_must_exist_true(self):
    # We should NOT be able to create a BuildFile instance against a dir called BUILD
    # in the default case.
    with self.assertRaises(BuildFile.MissingBuildFileError):
      BuildFile(self.root_dir, 'grandparent/BUILD')

  def test_directory_called_build_skipped(self):
    # Ensure the buildfiles found do not include grandparent/BUILD since it is a dir.
    buildfiles = BuildFile.scan_buildfiles(os.path.join(self.root_dir, 'grandparent'))

    self.assertEquals(OrderedSet([
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child1/BUILD'),
      self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),

      ]), buildfiles)

  def test_scan_buildfiles_exclude(self):
    buildfiles = BuildFile.scan_buildfiles(
      self.root_dir, '', spec_excludes=[
        os.path.join(self.root_dir, 'grandparent/parent/child1'),
        os.path.join(self.root_dir, 'grandparent/parent/child2')
      ])

    self.assertEquals([self.create_buildfile('BUILD'),
                       self.create_buildfile('BUILD.twitter'),
                       self.create_buildfile('grandparent/parent/BUILD'),
                       self.create_buildfile('grandparent/parent/BUILD.twitter'),
                       self.create_buildfile('grandparent/parent/child5/BUILD'),
                       ],
                      buildfiles)

  def test_invalid_root_dir_error(self):
    self.touch('BUILD')
    with self.assertRaises(BuildFile.InvalidRootDirError):
      BuildFile('tmp', 'grandparent/BUILD')

  def test_exception_class_hierarchy(self):
    """Exception handling code depends on the fact that all exceptions from BuildFile are
    subclassed from the BuildFileError base class.
    """
    self.assertIsInstance(BuildFile.InvalidRootDirError(), BuildFile.BuildFileError)
    self.assertIsInstance(BuildFile.MissingBuildFileError(), BuildFile.BuildFileError)

  def test_code(self):
    with safe_open(self.fullpath('BUILD.code'), 'w') as fp:
      fp.write('lib = java_library(name="jake", age=42)')
    build_file = self.create_buildfile('BUILD.code')

    parsed_locals = Compatibility.exec_function(build_file.code(), {'java_library': dict})
    lib = parsed_locals.pop('lib', None)
    self.assertEqual(dict(name='jake', age=42), lib)

  def test_code_syntax_error(self):
    with safe_open(self.fullpath('BUILD.badsyntax'), 'w') as fp:
      fp.write('java_library(name=if)')
    build_file = self.create_buildfile('BUILD.badsyntax')
    with self.assertRaises(SyntaxError) as e:
      build_file.code()
    self.assertEqual(build_file.full_path, e.exception.filename)
