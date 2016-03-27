# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six
from twitter.common.collections import OrderedSet

from pants.base.build_file import BuildFile
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.base.project_tree import ProjectTree
from pants.util.dirutil import safe_open
from pants_test.base.build_file_test_base import BuildFileTestBase


class FilesystemBuildFileTest(BuildFileTestBase):

  def setUp(self):
    super(FilesystemBuildFileTest, self).setUp()
    self._project_tree = FileSystemProjectTree(self.root_dir)
    self.buildfile = self.create_buildfile('grandparent/parent/BUILD')

  def test_build_files_family_lookup_1(self):
    buildfile = self.create_buildfile('grandparent/parent/BUILD.twitter')
    self.assertEquals({buildfile, self.buildfile},
                      set(self.get_build_files_family('grandparent/parent')))
    self.assertEquals({buildfile, self.buildfile},
                      set(self.get_build_files_family('grandparent/parent/')))

    self.assertEquals({self.create_buildfile('grandparent/parent/child2/child3/BUILD')},
                      set(self.get_build_files_family('grandparent/parent/child2/child3')))

  def test_build_files_family_lookup_2(self):
    self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
    ]), self.get_build_files_family('grandparent/parent'))

    buildfile = self.create_buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet([buildfile]), self.get_build_files_family('grandparent/parent/child2/child3'))

  def test_build_files_family_lookup_with_ignore(self):
    self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
    ]), self.get_build_files_family('grandparent/parent', build_ignore_patterns=['*.twitter']))

  def test_build_files_scan(self):
    self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child1/BUILD'),
        self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
        self.create_buildfile('grandparent/parent/child5/BUILD'),
    ]), self.scan_buildfiles('grandparent/parent'))

  def test_build_files_scan_with_relpath_ignore(self):
    buildfiles = self.scan_buildfiles('', build_ignore_patterns=[
        'grandparent/parent/child1',
        'grandparent/parent/child2'])
    self.assertEquals(OrderedSet([
        self.create_buildfile('BUILD'),
        self.create_buildfile('BUILD.twitter'),
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child5/BUILD'),
        self.create_buildfile('issue_1742/BUILD.sibling'),
    ]), buildfiles)

    buildfiles = self.scan_buildfiles('grandparent/parent', build_ignore_patterns=['grandparent/parent/child1'])
    self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
        self.create_buildfile('grandparent/parent/child5/BUILD'),
      ]), buildfiles)

  def test_build_files_scan_with_abspath_ignore(self):
    self.touch('parent/BUILD')
    self.assertEquals(OrderedSet([
      self.create_buildfile('BUILD'),
      self.create_buildfile('BUILD.twitter'),
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child1/BUILD'),
      self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),
      self.create_buildfile('issue_1742/BUILD.sibling'),
    ]), self.scan_buildfiles('', build_ignore_patterns=['/parent']))

  def test_build_files_scan_with_wildcard_ignore(self):
    self.assertEquals(OrderedSet([
      self.create_buildfile('BUILD'),
      self.create_buildfile('BUILD.twitter'),
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD.twitter'),
      self.create_buildfile('issue_1742/BUILD.sibling'),
    ]), self.scan_buildfiles('', build_ignore_patterns=['**/child*']))

  def test_build_files_scan_with_ignore_patterns(self):
    self.assertEquals(OrderedSet([
      self.create_buildfile('BUILD'),
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/child1/BUILD'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),
      self.create_buildfile('issue_1742/BUILD.sibling'),
    ]), self.scan_buildfiles('', build_ignore_patterns=['BUILD.twitter']))

  def test_subdir_ignore(self):
    self.touch('grandparent/child1/BUILD')

    self.assertEquals(OrderedSet([
      self.create_buildfile('BUILD'),
      self.create_buildfile('BUILD.twitter'),
      self.create_buildfile('grandparent/child1/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),
      self.create_buildfile('issue_1742/BUILD.sibling'),
    ]), self.scan_buildfiles('', build_ignore_patterns=['**/parent/child1']))

  def test_subdir_file_pattern_ignore(self):
    self.assertEquals(OrderedSet([
      self.create_buildfile('BUILD'),
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/child1/BUILD'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),
    ]), self.scan_buildfiles('', build_ignore_patterns=['BUILD.*']))

  def test_build_files_scan_with_non_default_relpath_ignore(self):
    self.assertEquals(OrderedSet([
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),
    ]), self.scan_buildfiles('grandparent/parent', build_ignore_patterns=['**/parent/child1']))

  def test_must_exist_true(self):
    with self.assertRaises(BuildFile.MissingBuildFileError):
      self.create_buildfile("path-that-does-not-exist/BUILD")
    with self.assertRaises(BuildFile.MissingBuildFileError):
      self.create_buildfile("path-that-does-exist/BUILD")
    with self.assertRaises(BuildFile.MissingBuildFileError):
      self.create_buildfile("path-that-does-exist/BUILD.invalid.suffix")

  def test_suffix_only(self):
    self.makedirs('suffix-test')
    self.touch('suffix-test/BUILD.suffix')
    self.touch('suffix-test/BUILD.suffix2')
    self.makedirs('suffix-test/child')
    self.touch('suffix-test/child/BUILD.suffix3')
    buildfile = self.create_buildfile('suffix-test/BUILD.suffix')
    self.assertEquals(OrderedSet([buildfile, self.create_buildfile('suffix-test/BUILD.suffix2')]),
        OrderedSet(self.get_build_files_family('suffix-test')))
    self.assertEquals(OrderedSet([self.create_buildfile('suffix-test/BUILD.suffix'),
        self.create_buildfile('suffix-test/BUILD.suffix2')]),
        self.get_build_files_family('suffix-test'))
    self.assertEquals(OrderedSet([self.create_buildfile('suffix-test/child/BUILD.suffix3')]),
        self.scan_buildfiles('suffix-test/child'))

  def test_directory_called_build_skipped(self):
    # Ensure the buildfiles found do not include grandparent/BUILD since it is a dir.
    buildfiles = self.scan_buildfiles('grandparent')

    self.assertEquals(OrderedSet([
      self.create_buildfile('grandparent/parent/BUILD'),
      self.create_buildfile('grandparent/parent/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child1/BUILD'),
      self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
      self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
      self.create_buildfile('grandparent/parent/child5/BUILD'),

      ]), buildfiles)

  def test_dir_is_primary(self):
    self.assertEqual([self.create_buildfile('issue_1742/BUILD.sibling')],
                     list(self.get_build_files_family('issue_1742')))

  def test_invalid_root_dir_error(self):
    self.touch('BUILD')
    with self.assertRaises(ProjectTree.InvalidBuildRootError):
      BuildFile(FileSystemProjectTree('tmp'), 'grandparent/BUILD')

  def test_exception_class_hierarchy(self):
    """Exception handling code depends on the fact that all exceptions from BuildFile are
    subclassed from the BuildFileError base class.
    """
    self.assertIsInstance(BuildFile.MissingBuildFileError(), BuildFile.BuildFileError)

  def test_code(self):
    with safe_open(self.fullpath('BUILD.code'), 'w') as fp:
      fp.write('lib = java_library(name="jake", age=42)')
    build_file = self.create_buildfile('BUILD.code')

    parsed_locals = {}
    six.exec_(build_file.code(), {'java_library': dict}, parsed_locals)
    lib = parsed_locals.pop('lib', None)
    self.assertEqual(dict(name='jake', age=42), lib)

  def test_code_syntax_error(self):
    with safe_open(self.fullpath('BUILD.badsyntax'), 'w') as fp:
      fp.write('java_library(name=if)')
    build_file = self.create_buildfile('BUILD.badsyntax')
    with self.assertRaises(SyntaxError) as e:
      build_file.code()
    self.assertEqual(build_file.full_path, e.exception.filename)
