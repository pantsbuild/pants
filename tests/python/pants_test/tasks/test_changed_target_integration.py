# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_file_dump, safe_mkdir, safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.git_util import initialize_repo


class ChangedTargetGoalsIntegrationTest(PantsRunIntegrationTest):
  @contextmanager
  def known_commits(self):
    """Creates an anonymous git repository under the buildroot."""
    with temporary_dir(root_dir=get_buildroot()) as worktree:
      rel_buildroot = fast_relpath(worktree, get_buildroot())
      with self.known_commits_in(worktree):
        yield worktree

  @contextmanager
  def known_commits_in(self, worktree, prefix=None):
    """Creates a git repository in the given target git root directory.

    If prefix is specified, it represents a tuple of a relative buildroot, and a relative source
    dir under that buildroot.
    """
    gitdir = os.path.join(worktree, '.git')
    if os.path.exists(gitdir):
      raise Exception('`known_commits_in` should not be used with an existing git repository.')

    buildroot = os.path.join(worktree, prefix[0]) if prefix else get_buildroot()
    sourcedir = os.path.join(worktree, prefix[0], prefix[1]) if prefix else worktree
    safe_mkdir(sourcedir)

    with safe_open(os.path.join(sourcedir, 'README'), 'w') as fp:
      fp.write('Just a test tree.')

    with initialize_repo(worktree=worktree, gitdir=gitdir) as git:
      src_file = os.path.join(sourcedir, 'src/java/org/pantsbuild/Class.java')
      with safe_open(src_file, 'w') as fp:
        fp.write(dedent("""
        package org.pantsbuild;

        class Class {
          static final int MEANING_OF_LIFE = 42;
        }
        """))

      src_build_file = os.path.join(sourcedir, 'src/java/org/pantsbuild/BUILD')
      src_address = fast_relpath(os.path.dirname(src_build_file), buildroot)
      with safe_open(src_build_file, 'w') as fp:
        fp.write("java_library(name='pantsbuild', sources=['Class.java'])")

      git.add(src_file, src_build_file)
      git.commit('Introduce Class.')

      test_file = os.path.join(sourcedir, 'tests/java/org/pantsbuild/ClassTest.java')
      with safe_open(test_file, 'w') as fp:
        fp.write(dedent("""
        package org.pantsbuild;

        import org.junit.Assert;
        import org.junit.Test;

        public class ClassTest {
          @Test public void test() {
            Assert.assertEquals(42, Class.MEANING_OF_LIFE);
          }
        }
        """))

      test_build_file = os.path.join(sourcedir, 'tests/java/org/pantsbuild/BUILD')
      with safe_open(test_build_file, 'w') as fp:
        fp.write(dedent("""
        jar_library(name='junit', jars=[jar('junit', 'junit', '4.12')])

        junit_tests(
          name='pantsbuild',
          sources=['ClassTest.java'],
          dependencies=[
            ':junit',
            '{}'
          ]
        )
        """).format(src_address))

      git.add(test_file, test_build_file)
      git.commit('Introduce ClassTest.')

      yield worktree

  _PACKAGE_PATH_PREFIX = os.sep + os.path.join('classes', 'org', 'pantsbuild')

  def find_classfile(self, workdir, filename):
    for root, dirs, files in os.walk(os.path.join(workdir, 'compile', 'zinc')):
      for f in files:
        candidate = os.path.join(root, f)
        if candidate.endswith(os.path.join(self._PACKAGE_PATH_PREFIX, filename)):
          return candidate

  def test_compile_changed(self):
    with self.known_commits():
      # Just look for changes in the 1st commit (addition of Class.java).
      cmd = ['--changed-diffspec=HEAD~2..HEAD~1', 'compile']

      with self.temporary_workdir() as workdir:
        # Nothing exists.
        self.assertIsNone(self.find_classfile(workdir, 'Class.class'))
        self.assertIsNone(self.find_classfile(workdir, 'ClassTest.class'))

        run = self.run_pants_with_workdir(cmd, workdir)
        self.assert_success(run)

        # The directly changed target's produced classfile exists.
        self.assertIsNotNone(self.find_classfile(workdir, 'Class.class'))
        self.assertIsNone(self.find_classfile(workdir, 'ClassTest.class'))

      with self.temporary_workdir() as workdir:
        # Nothing exists.
        self.assertIsNone(self.find_classfile(workdir, 'Class.class'))
        self.assertIsNone(self.find_classfile(workdir, 'ClassTest.class'))

        run = self.run_pants_with_workdir(cmd + ['--changed-include-dependees=direct'], workdir)
        self.assert_success(run)

        # The changed target's and its direct dependees' (eg its tests) classfiles exist.
        # NB: This highlights a quirk of test-changed (really ChangeCalculator): it uses a
        # potentially historical diff to calculate changed files but it always uses BUILD files
        # from HEAD to determine dependees.  As such, in this case, although neither ClassTest.java
        # nor its BUILD file existed in HEAD~2...HEAD~1 - they do now and so are seen as dependees
        # of Class.java.
        self.assertIsNotNone(self.find_classfile(workdir, 'Class.class'))
        self.assertIsNotNone(self.find_classfile(workdir, 'ClassTest.class'))

  def test_test_changed(self):
    with self.known_commits() as worktree, self.temporary_workdir(rootdir=worktree) as workdir:
      cmd = ['--changed-diffspec=HEAD~2..HEAD~1', 'test']
      junit_out = os.path.join(get_buildroot(), 'dist', 'test', 'junit',
                               'org.pantsbuild.ClassTest.out.txt')

      self.assertFalse(os.path.exists(junit_out))

      run = self.run_pants_with_workdir(cmd, workdir)
      self.assert_success(run)

      self.assertFalse(os.path.exists(junit_out))

      run = self.run_pants_with_workdir(cmd + ['--changed-include-dependees=direct'], workdir)
      self.assert_success(run)

      self.assertTrue(os.path.exists(junit_out))

  def test_list_changed(self):
    with self.known_commits() as worktree, self.temporary_workdir(rootdir=worktree) as workdir:
      rel_buildroot = fast_relpath(worktree, get_buildroot())
      cmd = ['--changed-diffspec=HEAD~2..HEAD~1', 'list']
      run = self.run_pants_with_workdir(cmd, workdir)
      self.assert_success(run)
      self.assertEquals(
          {os.path.join(rel_buildroot, 'src/java/org/pantsbuild:pantsbuild')},
          set(run.stdout_data.splitlines()),
        )

  def test_list_changed_with_buildroot_ne_gitroot(self):
    # Create a temporary directory, create a mock buildroot in a subdirectory, and then
    # initialize a git repository _above_ the buildroot in the original temp directory.
    with temporary_dir(root_dir=get_buildroot()) as worktree, \
         self.mock_buildroot(root_dir=worktree) as mock_buildroot:
      # The mock buildroot will have all the same contents as the "real" buildroot, so we
      # create commits under it in a non-colliding directory name.
      # TODO: Could maybe make another temp directory here.
      rel_sources_dir = 'changed-sources'
      rel_buildroot = fast_relpath(mock_buildroot.new_buildroot, worktree)
      with self.known_commits_in(worktree, prefix=(rel_buildroot, rel_sources_dir)), \
           mock_buildroot.pushd():

        # Add untracked files both inside and outside of the buildroot to cover the case described in #6301.
        safe_file_dump(os.path.join(mock_buildroot.new_buildroot, rel_sources_dir, 'this-is-untracked-inside-the-buildroot'), '')
        safe_file_dump(os.path.join(worktree, 'this-is-untracked-outside-the-buildroot'), '')

        # `--changed-parent` uses a separate codepath from `--changed-diffspec`, so cover it
        # independently.
        for cmd in (['--changed-diffspec=HEAD~1..HEAD', 'list'], ['--changed-parent=HEAD~1', 'list']):
          run = self.run_pants_with_workdir(
            cmd,
            workdir=os.path.join(mock_buildroot.new_buildroot, '.pants.d'),
            build_root=mock_buildroot.new_buildroot,
          )

          self.assert_success(run)
          self.assertEquals(
              {
                  os.path.join(rel_sources_dir, 'tests/java/org/pantsbuild:pantsbuild'),
                  os.path.join(rel_sources_dir, 'tests/java/org/pantsbuild:junit'),
              },
              set(run.stdout_data.splitlines()),
            )
