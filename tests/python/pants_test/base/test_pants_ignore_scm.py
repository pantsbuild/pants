# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.base.scm_project_tree import ScmProjectTree
from pants.scm.git import Git
from pants_test.base.project_tree_test_base import ProjectTreeTestBase


class ScmPantsIgnoreTest(ProjectTreeTestBase):

  def setUp(self):
    super(ScmPantsIgnoreTest, self).setUp()
    subprocess.check_call(['git', 'init'])
    subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
    subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m' 'initial commit'])

  def test_ignore_pattern_blank_line(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', [""])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'apple', 'orange', 'banana',
                       'fruit/apple', 'fruit/orange', 'fruit/banana',
                       'fruit/fruit/apple', 'fruit/fruit/orange', 'fruit/fruit/banana',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_comment(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["#fruit", "#apple", "#banana"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'apple', 'orange', 'banana',
                       'fruit/apple', 'fruit/orange', 'fruit/banana',
                       'fruit/fruit/apple', 'fruit/fruit/orange', 'fruit/fruit/banana',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_negate(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["*an*", "!*na*"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'apple', 'banana',
                       'fruit/apple', 'fruit/banana',
                       'fruit/fruit/apple', 'fruit/fruit/banana',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_ends_with_slash(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["fruit/"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'apple', 'banana', 'orange',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_no_slash(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["fruit"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'apple', 'banana', 'orange'}, set(files_list))

  def test_ignore_pattern_has_slash(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["fruit/apple"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

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
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["/apple"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'banana', 'orange',
                       'fruit/apple', 'fruit/banana', 'fruit/orange',
                       'fruit/fruit/apple', 'fruit/fruit/banana', 'fruit/fruit/orange',
                       'grocery/fruit'
                       }, set(files_list))

  def test_ignore_pattern_wildcard(self):
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["/*e"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

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
    self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD', ["/**/apple"])
    files_list = []
    for root, dirs, files in self._project_tree.walk(''):
      for file in files:
        files_list.append(os.path.normpath(os.path.join(root, file)))

    self.assertEquals({'banana', 'orange',
                       'fruit/banana', 'fruit/orange',
                       'fruit/fruit/banana', 'fruit/fruit/orange',
                       'grocery/fruit'
                       }, set(files_list))
