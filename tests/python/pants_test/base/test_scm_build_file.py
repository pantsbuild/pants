# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess

from twitter.common.collections import OrderedSet

from pants.base.scm_project_tree import ScmProjectTree
from pants.scm.git import Git
from pants.util.contextutil import pushd
from pants_test.base.build_file_test_base import BuildFileTestBase


class ScmBuildFileTest(BuildFileTestBase):

  def test_build_file_rev(self):
    # Test that the build_file_rev global option works.  Because the
    # test framework does not yet support bootstrap options, this test
    # in fact just directly calls ScmBuildFile.set_rev.

    with pushd(self.root_dir):
      subprocess.check_call(['git', 'init'])
      subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
      subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
      subprocess.check_call(['git', 'add', '.'])
      subprocess.check_call(['git', 'commit', '-m' 'initial commit'])

      subprocess.check_call(['rm', '-rf', 'path-that-does-exist',
                             'grandparent', 'BUILD', 'BUILD.twitter'])

      self._project_tree = ScmProjectTree(self.root_dir, Git(worktree=self.root_dir), 'HEAD')

      my_buildfile = self.create_buildfile('grandparent/parent/BUILD')
      buildfile = self.create_buildfile('grandparent/parent/BUILD.twitter')

      self.assertEquals(OrderedSet([my_buildfile, buildfile]),
                        OrderedSet(self.get_build_files_family('grandparent/parent')))

      self.assertEquals(OrderedSet([self.create_buildfile('grandparent/parent/child2/child3/BUILD')]),
                        OrderedSet(self.get_build_files_family('grandparent/parent/child2/child3')))

      buildfiles = self.scan_buildfiles('grandparent')

      self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child1/BUILD'),
        self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
        self.create_buildfile('grandparent/parent/child5/BUILD'),
      ]), buildfiles)
