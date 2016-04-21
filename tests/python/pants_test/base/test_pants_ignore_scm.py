# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess
import unittest

from pants.base.scm_project_tree import ScmProjectTree
from pants.scm.git import Git
from pants_test.base.pants_ignore_test_base import PantsIgnoreTestBase


class ScmPantsIgnoreTest(unittest.TestCase, PantsIgnoreTestBase):
  def mk_project_tree(self, build_root, ignore_patterns=[]):
    return ScmProjectTree(build_root, Git(worktree=build_root), 'HEAD', ignore_patterns)

  def setUp(self):
    super(ScmPantsIgnoreTest, self).setUp()
    self.prepare()
    subprocess.check_call(['git', 'init'])
    subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
    subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m' 'initial commit'])

  def tearDown(self):
    super(ScmPantsIgnoreTest, self).tearDown()
    self.cleanup()

  def test_folder_slash(self):
    self._project_tree = self.mk_project_tree(self.root_dir, ["fruit/"])

    self.assertEquals(set(), set(self._project_tree.glob1('fruit/', '*')))
