# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.base.project_tree_test_base import ProjectTreeTestBase


class PantsIgnoreTestBase(ProjectTreeTestBase):
  def prepare(self):
    self.base_dir = self.make_base_dir()
    self.root_dir = os.path.join(self.base_dir, 'root')

    # make 'root/'
    self.makedirs('')

    # make 'root/...'
    self.touch('apple')
    self.touch('orange')
    self.touch('banana')

    # make 'root/fruit/'
    self.makedirs('fruit')

    # make 'root/fruit/...'
    self.touch('fruit/apple')
    self.touch('fruit/orange')
    self.touch('fruit/banana')

    # make 'root/fruit/fruit/'
    self.makedirs('fruit/fruit')

    # make 'root/fruit/fruit/...'
    self.touch('fruit/fruit/apple')
    self.touch('fruit/fruit/orange')
    self.touch('fruit/fruit/banana')

    self.makedirs('grocery')
    self.touch('grocery/fruit')

    self.cwd = os.getcwd()
    os.chdir(self.root_dir)

  def cleanup(self):
    os.chdir(self.cwd)
    self.rmdirs(self.base_dir)

  def test_ignore_pattern_blank_line(self):
    self._project_tree = self.mk_project_tree(self.root_dir, [""])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'apple', 'orange', 'banana',
                       'fruit/apple', 'fruit/orange', 'fruit/banana',
                       'fruit/fruit/apple', 'fruit/fruit/orange', 'fruit/fruit/banana',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_comment(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["#fruit", "#apple", "#banana"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'apple', 'orange', 'banana',
                       'fruit/apple', 'fruit/orange', 'fruit/banana',
                       'fruit/fruit/apple', 'fruit/fruit/orange', 'fruit/fruit/banana',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_negate(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["*an*", "!*na*"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'apple', 'banana',
                       'fruit/apple', 'fruit/banana',
                       'fruit/fruit/apple', 'fruit/fruit/banana',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_ends_with_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["fruit/"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'apple', 'banana', 'orange',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_no_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["fruit"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'apple', 'banana', 'orange'}, set(files_list))

  def test_ignore_pattern_has_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["fruit/apple"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'apple', 'banana', 'orange',
                       'fruit/banana', 'fruit/orange',
                       'fruit/fruit/apple', 'fruit/fruit/banana', 'fruit/fruit/orange',
                       'grocery/fruit'
                       }, set(files_list))

    files_list = self._project_tree.glob1("fruit", "*")
    self.assertEquals({'banana', 'orange', 'fruit'}, set(files_list))

    files_list = self._project_tree.listdir("fruit")
    self.assertEquals({'banana', 'orange', 'fruit'}, set(files_list))

    with self.assertRaises(self._project_tree.AccessIgnoredPathError):
      self._project_tree.content("fruit/apple")

  def test_ignore_pattern_leading_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["/apple"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'banana', 'orange',
                       'fruit/apple', 'fruit/banana', 'fruit/orange',
                       'fruit/fruit/apple', 'fruit/fruit/banana', 'fruit/fruit/orange',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_wildcard(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["/*e"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'banana',
                       'fruit/apple', 'fruit/banana', 'fruit/orange',
                       'fruit/fruit/apple', 'fruit/fruit/banana', 'fruit/fruit/orange',
                       'grocery/fruit'
                       }, set(files_list))

    files_list = self._project_tree.glob1("", "*e")
    self.assertEquals(set(), set(files_list))

    files_list = self._project_tree.listdir("")
    self.assertEquals({'banana', 'fruit', 'grocery'}, set(files_list))

  def test_ignore_pattern_two_asterisks(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["/**/apple"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.join(root, file))

    self.assertEquals({'banana', 'orange',
                       'fruit/banana', 'fruit/orange',
                       'fruit/fruit/banana', 'fruit/fruit/orange',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_dir_path_ignore_1(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["fruit/fruit/"])

    self.assertFalse(self._project_tree.isdir('fruit/fruit'))
    self.assertFalse(self._project_tree.exists('fruit/fruit'))
    self.assertEquals({'apple', 'banana', 'orange'}, set(self._project_tree.glob1('fruit', '*')))
    self.assertEquals({'apple', 'banana', 'orange'}, set(self._project_tree.listdir('fruit')))

  def test_ignore_dir_path_ignore_2(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["fruit/"])

    self.assertFalse(self._project_tree.isdir('fruit'))
    self.assertFalse(self._project_tree.exists('fruit'))
    self.assertEquals({'apple', 'banana', 'orange', 'grocery'}, set(self._project_tree.glob1('', '*')))
    self.assertEquals({'apple', 'banana', 'orange', 'grocery'}, set(self._project_tree.listdir('')))
