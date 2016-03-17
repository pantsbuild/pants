# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time

from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, touch
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CacheCleanupIntegrationTest(PantsRunIntegrationTest):

  def create_platform_args(self, version):
    return [("""--jvm-platform-platforms={{'default': {{'target': '{version}'}}}}"""
             .format(version=version)),
            '--jvm-platform-default-platform=default']

  def test_buildcache_leave_one(self):
    """Ensure that max-old of 1 removes all but one files"""

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, ZincCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main')

      touch(os.path.join(artifact_dir, 'old_cache_test1'))
      touch(os.path.join(artifact_dir, 'old_cache_test2'))
      touch(os.path.join(artifact_dir, 'old_cache_test3'))
      touch(os.path.join(artifact_dir, 'old_cache_test4'))
      touch(os.path.join(artifact_dir, 'old_cache_test5'))

      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(self.create_platform_args(6) +
                                 ['compile.zinc',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-max-entries-per-target=1'],
                                 config=config)
      self.assert_success(pants_run)

      # One artifact for java 6
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for java 7
      pants_run = self.run_pants(self.create_platform_args(7) +
                                 ['compile.zinc',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-max-entries-per-target=1'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 7
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

  def test_buildcache_leave_none(self):
    """Ensure that max-old of zero removes all files

    This test should ensure that conditional doesn't change to the simpler test of if max_old since
    we need to handle zero as well.
    """

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, ZincCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main')

      touch(os.path.join(artifact_dir, 'old_cache_test1'))
      touch(os.path.join(artifact_dir, 'old_cache_test2'))
      touch(os.path.join(artifact_dir, 'old_cache_test3'))
      touch(os.path.join(artifact_dir, 'old_cache_test4'))
      touch(os.path.join(artifact_dir, 'old_cache_test5'))

      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(self.create_platform_args(6) +
                                 ['compile.zinc',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-max-entries-per-target=0'],
                                 config=config)
      self.assert_success(pants_run)

      # Cache cleanup disabled for 0

      self.assertEqual(len(os.listdir(artifact_dir)), 6)

      # Rerun for java 7
      pants_run = self.run_pants(self.create_platform_args(7) +
                                 ['compile.zinc',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-max-entries-per-target=0'],
                                 config)
      self.assert_success(pants_run)

      # Cache cleanup disabled for 0
      self.assertEqual(len(os.listdir(artifact_dir)), 7)

  def test_workdir_stale_builds_cleanup(self):
    """Ensure that current and previous build result_dirs and the newest `--workdir-max-build-entries` number of dirs
    will be kept, and the rest will be purged.
    """

    with temporary_dir() as tmp_dir:
      workdir = os.path.join(tmp_dir, '.pants.d')
      pants_run = self.run_pants_with_workdir(['compile',
                                               'export-classpath',
                                               'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                               ], workdir)
      self.assert_success(pants_run)

      # Use the static exported classpath symlink to access the artifact in workdir
      # in order to avoid computing hashed task version used in workdir.
      classpath = 'dist/export-classpath/testprojects.src.java.org.pantsbuild.testproject.unicode.main.main-0.jar'

      # <workdir>/compile/zinc/d4600a981d5d/testprojects.src.java.org.pantsbuild.testproject.unicode.main.main/1a317a2504f6/z.jar'
      jar_path_in_pantsd = os.path.realpath(classpath)

      # <workdir>/compile/zinc/d4600a981d5d/testprojects.src.java.org.pantsbuild.testproject.unicode.main.main/
      target_dir_in_pantsd = os.path.dirname(os.path.dirname(jar_path_in_pantsd))

      safe_mkdir(os.path.join(target_dir_in_pantsd, 'old_cache_test1_dir'))
      safe_mkdir(os.path.join(target_dir_in_pantsd, 'old_cache_test2_dir'))
      safe_mkdir(os.path.join(target_dir_in_pantsd, 'old_cache_test3_dir'))
      time.sleep(1.1)
      safe_mkdir(os.path.join(target_dir_in_pantsd, 'old_cache_test4_dir'))
      safe_mkdir(os.path.join(target_dir_in_pantsd, 'old_cache_test5_dir'))

      # stable symlink, current version directory, and synthetically created directories.
      self.assertTrue(os.path.exists(os.path.join(target_dir_in_pantsd, 'current')))
      self.assertEqual(len(os.listdir(target_dir_in_pantsd)), 7)

      max_entries_per_target = 2
      # 2nd run with --compile-zinc-debug-symbols will invalidate previous build thus triggering the clean up.
      pants_run_2 = self.run_pants_with_workdir(['compile',
                                                 'export-classpath',
                                                 'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                                 '--compile-zinc-debug-symbols',
                                                 '--workdir-max-build-entries={}'.format(max_entries_per_target)
                                                 ], workdir)
      self.assert_success(pants_run_2)
      # stable, current, previous builds stay, and 2 newest dirs
      self.assertEqual(len(os.listdir(target_dir_in_pantsd)), 5)
      self.assertTrue(os.path.exists(os.path.join(target_dir_in_pantsd, 'current')))
      self.assertTrue(os.path.exists(os.path.join(target_dir_in_pantsd, 'old_cache_test4_dir')))
      self.assertTrue(os.path.exists(os.path.join(target_dir_in_pantsd, 'old_cache_test5_dir')))

      self.assertFalse(os.path.exists(os.path.join(target_dir_in_pantsd, 'old_cache_test1_dir')))
      self.assertFalse(os.path.exists(os.path.join(target_dir_in_pantsd, 'old_cache_test2_dir')))
      self.assertFalse(os.path.exists(os.path.join(target_dir_in_pantsd, 'old_cache_test3_dir')))
