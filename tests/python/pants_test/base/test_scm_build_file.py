# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from twitter.common.collections import OrderedSet

from pants.base.build_file import BuildFile
from pants.base.scm_build_file import ScmBuildFile
from pants.base.scm_file_system import ScmFilesystem
from pants.scm.git import Git
from pants.util.contextutil import pushd
from pants_test.base.build_file_test_base import BuildFileTestBase


class ScmBuildFileTest(BuildFileTestBase):

  def setUp(self):
    super(ScmBuildFileTest, self).setUp()

  def create_file_system(self):
    return ScmFilesystem(Git(worktree=self.root_dir), 'HEAD')

  def create_buildfile(self, path):
    # todo: remove after deprication
    BuildFile._scm_cls = ScmBuildFile

    return BuildFile.create(self._file_system, self.root_dir, path)

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

      my_buildfile = self.create_buildfile('grandparent/parent/BUILD')
      buildfile = self.create_buildfile('grandparent/parent/BUILD.twitter')

      self.assertEquals(OrderedSet([buildfile]), OrderedSet(my_buildfile.siblings()))
      self.assertEquals(OrderedSet([my_buildfile]), OrderedSet(buildfile.siblings()))

      buildfile = self.create_buildfile('grandparent/parent/child2/child3/BUILD')
      self.assertEquals(OrderedSet(), OrderedSet(buildfile.siblings()))

      buildfiles = self.scan_buildfiles(os.path.join(self.root_dir, 'grandparent'))

      self.assertEquals(OrderedSet([
        self.create_buildfile('grandparent/parent/BUILD'),
        self.create_buildfile('grandparent/parent/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child1/BUILD'),
        self.create_buildfile('grandparent/parent/child1/BUILD.twitter'),
        self.create_buildfile('grandparent/parent/child2/child3/BUILD'),
        self.create_buildfile('grandparent/parent/child5/BUILD'),
      ]), buildfiles)
