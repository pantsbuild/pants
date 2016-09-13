# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.git_util import initialize_repo


class ChangedTargetGoalsIntegrationTest(PantsRunIntegrationTest):
  @contextmanager
  def known_commits(self):
    with temporary_dir(root_dir=get_buildroot()) as worktree:
      with safe_open(os.path.join(worktree, 'README'), 'w') as fp:
        fp.write('Just a test tree.')

      with initialize_repo(worktree=worktree, gitdir=os.path.join(worktree, '.git')) as git:
        src_file = os.path.join(worktree, 'src/java/org/pantsbuild/Class.java')
        with safe_open(src_file, 'w') as fp:
          fp.write(dedent("""
          package org.pantsbuild;

          class Class {
            static final int MEANING_OF_LIFE = 42;
          }
          """))

        src_build_file = os.path.join(worktree, 'src/java/org/pantsbuild/BUILD')
        with safe_open(src_build_file, 'w') as fp:
          fp.write("java_library(name='pantsbuild', sources=['Class.java'])")

        git.add(src_file, src_build_file)
        git.commit('Introduce Class.')

        test_file = os.path.join(worktree, 'tests/java/org/pantsbuild/ClassTest.java')
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

        test_build_file = os.path.join(worktree, 'tests/java/org/pantsbuild/BUILD')
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
          """).format(os.path.relpath(os.path.dirname(src_build_file), get_buildroot())))

        git.add(test_file, test_build_file)
        git.commit('Introduce ClassTest.')

        yield

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
      cmd = ['compile-changed', '--diffspec=HEAD~2..HEAD~1']

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

        run = self.run_pants_with_workdir(cmd + ['--include-dependees=direct'], workdir)
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
    with self.known_commits(), self.temporary_workdir() as workdir:
      cmd = ['test-changed', '--diffspec=HEAD~2..HEAD~1']
      junit_out = os.path.join(workdir, 'test', 'junit', 'org.pantsbuild.ClassTest.out.txt')

      self.assertFalse(os.path.exists(junit_out))

      run = self.run_pants_with_workdir(cmd, workdir)
      self.assert_success(run)

      self.assertFalse(os.path.exists(junit_out))

      run = self.run_pants_with_workdir(cmd + ['--include-dependees=direct'], workdir)
      self.assert_success(run)

      self.assertTrue(os.path.exists(junit_out))
