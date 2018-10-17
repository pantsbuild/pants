# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants_test.base.project_tree_test_base import ProjectTreeTestBase


class PantsIgnoreTestBase(ProjectTreeTestBase):
  def prepare(self):
    self.base_dir = self.make_base_dir()
    self.root_dir = os.path.join(self.base_dir, 'root')

    self._all_files = set()

    # Make 'root/'.
    self.makedirs('')

    # Make 'root/...'.
    files = ['apple', 'orange', 'banana']
    self.touch_list(files)
    self._all_files |= set(files)

    # Make 'root/fruit/'.
    self.makedirs('fruit')

    # Make 'root/fruit/...'.
    files = ['fruit/apple', 'fruit/orange', 'fruit/banana']
    self.touch_list(files)
    self._all_files |= set(files)

    # Make 'root/fruit/fruit/'.
    self.makedirs('fruit/fruit')

    # Make 'root/fruit/fruit/...'.
    files = ['fruit/fruit/apple', 'fruit/fruit/orange', 'fruit/fruit/banana']
    self.touch_list(files)
    self._all_files |= set(files)

    # Make 'root/grocery/'.
    self.makedirs('grocery')

    # Make 'root/grocery/fruit'.
    files = ['grocery/fruit']
    self.touch_list(files)
    self._all_files |= set(files)

    self.cwd = os.getcwd()
    os.chdir(self.root_dir)

  def cleanup(self):
    os.chdir(self.cwd)
    self.rm_base_dir()

  def _walk_tree(self):
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))
    return files_list

  def test_ignore_pattern_blank_line(self):
    self._project_tree = self.mk_project_tree(self.root_dir, [''])
    files_list = self._walk_tree()

    self.assertEqual(self._all_files, set(files_list))

  def test_ignore_pattern_comment(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['#fruit', '#apple', '#banana'])
    files_list = self._walk_tree()

    self.assertEqual(self._all_files, set(files_list))

  def test_ignore_pattern_negate(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['*an*', '!*na*'])
    files_list = self._walk_tree()

    self.assertEqual(
      self._all_files - {'orange', 'fruit/orange', 'fruit/fruit/orange'},
      set(files_list)
    )

  def test_ignore_pattern_ends_with_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['fruit/'])
    files_list = self._walk_tree()

    self.assertEqual(
      self._all_files - {'fruit/apple', 'fruit/banana', 'fruit/orange',
                         'fruit/fruit/apple', 'fruit/fruit/banana', 'fruit/fruit/orange'},
      set(files_list)
    )

  def test_ignore_pattern_no_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['fruit'])
    files_list = self._walk_tree()

    self.assertEqual(
      self._all_files - {'fruit/apple', 'fruit/banana', 'fruit/orange',
                         'fruit/fruit/apple', 'fruit/fruit/banana', 'fruit/fruit/orange',
                         'grocery/fruit'},
      set(files_list)
    )

  def test_ignore_pattern_has_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['fruit/apple'])
    files_list = self._walk_tree()

    self.assertEqual(self._all_files - {'fruit/apple'}, set(files_list))

    files_list = self._project_tree.glob1('fruit', '*')
    self.assertEqual({'banana', 'orange', 'fruit'}, set(files_list))

    files_list = [s.path for s in self._project_tree.scandir('fruit')]
    self.assertEqual({'fruit/banana', 'fruit/orange', 'fruit/fruit'}, set(files_list))

    with self.assertRaises(self._project_tree.AccessIgnoredPathError):
      self._project_tree.content('fruit/apple')

  def test_ignore_pattern_leading_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['/apple'])
    files_list = self._walk_tree()

    self.assertEqual(self._all_files - {'apple'}, set(files_list))

  def test_ignore_pattern_leading_and_trailing_slashes(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['/apple/'])
    files_list = self._walk_tree()
    # Pattern '/apple/' should only exclude directory `/apple`.
    # File `/apple` is not excluded.
    self.assertEqual(self._all_files, set(files_list))

  def test_ignore_pattern_leading_slash_should_exclude_subdirs(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['/fruit'])
    files_list = self._walk_tree()

    # root level `/fruit` and its subdirs are excluded.
    # non root level `/grocery/fruit` is included.
    self.assertEqual(
      self._all_files - {'fruit/apple',
                         'fruit/banana',
                         'fruit/orange',
                         'fruit/fruit/apple',
                         'fruit/fruit/banana',
                         'fruit/fruit/orange'},
      set(files_list)
    )

  def test_ignore_pattern_wildcard(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['/*e'])
    files_list = self._walk_tree()

    self.assertEqual(self._all_files - {'apple', 'orange'}, set(files_list))

    files_list = self._project_tree.glob1('', '*e')
    self.assertEqual(set(), set(files_list))

    files_list = [s.path for s in self._project_tree.scandir('')]
    self.assertEqual({'banana', 'fruit', 'grocery'}, set(files_list))

  def test_ignore_pattern_two_asterisks(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['/**/apple'])
    files_list = self._walk_tree()

    self.assertEqual(self._all_files - {'apple', 'fruit/apple', 'fruit/fruit/apple'}, set(files_list))

  def test_ignore_dir_path_ignore_1(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['fruit/fruit/'])

    self.assertFalse(self._project_tree.isdir('fruit/fruit'))
    self.assertFalse(self._project_tree.exists('fruit/fruit'))
    self.assertEqual({'apple', 'banana', 'orange'}, set(self._project_tree.glob1('fruit', '*')))
    self.assertEqual({'fruit/apple', 'fruit/banana', 'fruit/orange'},
                      {s.path for s in self._project_tree.scandir('fruit')})

  def test_ignore_dir_path_ignore_2(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ['fruit/'])

    self.assertFalse(self._project_tree.isdir('fruit'))
    self.assertFalse(self._project_tree.exists('fruit'))
    self.assertEqual({'apple', 'banana', 'orange', 'grocery'}, set(self._project_tree.glob1('', '*')))
    self.assertEqual({'apple', 'banana', 'orange', 'grocery'},
                      {s.path for s in self._project_tree.scandir('')})
