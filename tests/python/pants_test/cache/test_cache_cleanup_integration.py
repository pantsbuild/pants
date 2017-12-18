# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import time

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_delete, safe_mkdir, touch
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CacheCleanupIntegrationTest(PantsRunIntegrationTest):

  def _create_platform_args(self, version):
    return [("""--jvm-platform-platforms={{'default': {{'target': '{version}'}}}}"""
             .format(version=version)),
            '--jvm-platform-default-platform=default']

  def _run_pants_get_artifact_dir(self, args, cache_dir, subdir, num_files_to_insert, expected_num_files, config=None, prev_dirs=[]):
    """Run Pants with the given `args` and `config`, delete the results, add
    some files, then run pants again and ensure there are exactly
    `expected_num_files` in the output.

    Pants needs to be run twice because we don't know what the results directory
    will be named before we run Pants, and we want to insert files into that
    specific directory to test cache cleanup procedures.
    """
    self.assert_success(self.run_pants(args, config=config))

    artifact_base_dir = self.get_cache_subdir(cache_dir, other_dirs=prev_dirs)
    artifact_dir = os.path.join(artifact_base_dir, subdir)

    for tgz in glob.glob(os.path.join(artifact_dir, '*.tgz')):
      safe_delete(tgz)
    for i in range(0, num_files_to_insert):
      touch(os.path.join(artifact_dir, 'old_cache_test{}'.format(i + 1)))

    self.assert_success(self.run_pants(args, config=config))
    self.assertEqual(len(os.listdir(artifact_dir)), expected_num_files)

    return artifact_base_dir

  def test_buildcache_leave_one(self):
    """Ensure that max-old of 1 removes all but one files"""

    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      java_6_args = self._create_platform_args(6) + [
        'compile.zinc',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
        '--cache-max-entries-per-target=1',
      ]
      java_6_artifact_base_dir = self._run_pants_get_artifact_dir(
        java_6_args,
        cache_dir,
        'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
        num_files_to_insert=5,
        # One artifact for java 6
        expected_num_files=1,
        config=config,
      )

      # Rerun for java 7
      java_7_args = self._create_platform_args(7) + [
        'compile.zinc',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
        '--cache-max-entries-per-target=1',
      ]
      self._run_pants_get_artifact_dir(
        java_7_args,
        cache_dir,
        'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
        num_files_to_insert=2,
        # One artifact for java 6
        expected_num_files=1,
        config=config,
        # java 7 platform args should change the name of the cache directory
        prev_dirs=[java_6_artifact_base_dir],
      )

  def test_buildcache_leave_none(self):
    """Ensure that max-old of zero removes all files

    This test should ensure that conditional doesn't change to the simpler test of if max_old since
    we need to handle zero as well.
    """

    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      java_6_args = self._create_platform_args(6) + [
        'compile.zinc',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
        '--cache-max-entries-per-target=0',
      ]
      java_6_artifact_base_dir = self._run_pants_get_artifact_dir(
        java_6_args,
        cache_dir,
        'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
        num_files_to_insert=5,
        # Cache cleanup disabled for 0
        expected_num_files=6,
        config=config,
      )

      # Rerun for java 7
      java_7_args = self._create_platform_args(7) + [
        'compile.zinc',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
        '--cache-max-entries-per-target=0',
      ]
      self._run_pants_get_artifact_dir(
        java_7_args,
        cache_dir,
        'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
        num_files_to_insert=2,
        # Cache cleanup disabled for 0
        expected_num_files=3,
        config=config,
        # java 7 platform args should change the name of the cache directory
        prev_dirs=[java_6_artifact_base_dir],
      )

  def test_workdir_stale_builds_cleanup(self):
    """Ensure that current and previous build result_dirs and the newest `--workdir-max-build-entries` number of dirs
    will be kept, and the rest will be purged.
    """

    with temporary_dir() as tmp_dir:
      workdir = os.path.join(tmp_dir, '.pants.d')

      self.assert_success(self.run_pants_with_workdir([
        'compile',
        'export-classpath',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
      ], workdir))

      # Use the static exported classpath symlink to access the artifact in workdir
      # in order to avoid computing hashed task version used in workdir.
      classpath = 'dist/export-classpath/testprojects.src.java.org.pantsbuild.testproject.unicode.main.main-0.jar'

      # <workdir>/compile/zinc/d4600a981d5d/testprojects.src.java.org.pantsbuild.testproject.unicode.main.main/1a317a2504f6/z.jar'
      jar_path_in_pantsd = os.path.realpath(classpath)

      # <workdir>/compile/zinc/d4600a981d5d/testprojects.src.java.org.pantsbuild.testproject.unicode.main.main/
      target_dir_in_pantsd = os.path.dirname(os.path.dirname(jar_path_in_pantsd))

      old_cache_dirnames = set([
        'old_cache_test1_dir/',
        'old_cache_test2_dir/',
        'old_cache_test3_dir/',
      ])
      new_cache_dirnames = set([
        'old_cache_test4_dir/',
        'old_cache_test5_dir/',
      ])
      old_cache_entries = {os.path.join(target_dir_in_pantsd, subdir) for subdir in old_cache_dirnames}
      new_cache_entries = {os.path.join(target_dir_in_pantsd, subdir) for subdir in new_cache_dirnames}
      for old_entry in old_cache_entries:
        safe_mkdir(old_entry)
      # sleep for a bit so these files are all newer than the other ones
      time.sleep(1.1)
      for new_entry in new_cache_entries:
        safe_mkdir(new_entry)
      expected_dirs = set([os.path.join(target_dir_in_pantsd, 'current/')]) | old_cache_entries | new_cache_entries

      # stable symlink, current version directory, and synthetically created directories.
      remaining_cache_dir_fingerprinted = self.get_cache_subdir(target_dir_in_pantsd, other_dirs=expected_dirs)
      fingerprinted_realdir = os.path.realpath(os.path.join(target_dir_in_pantsd, 'current'))
      self.assertEqual(
        fingerprinted_realdir,
        remaining_cache_dir_fingerprinted.rstrip('/'))

      max_entries_per_target = 2
      self.assert_success(self.run_pants_with_workdir([
        'compile',
        'export-classpath',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
        '--workdir-max-build-entries={}'.format(max_entries_per_target)
      ], workdir))

      # stable (same as before), current, and 2 newest dirs
      self.assertEqual(os.path.dirname(os.path.dirname(os.path.realpath(classpath))), target_dir_in_pantsd)
      newest_expected_dirs = expected_dirs - old_cache_entries
      other_cache_dir_fingerprinted = self.get_cache_subdir(target_dir_in_pantsd, other_dirs=newest_expected_dirs)
      self.assertEqual(other_cache_dir_fingerprinted, remaining_cache_dir_fingerprinted)
      self.assertEqual(
        os.path.realpath(os.path.join(target_dir_in_pantsd, 'current')),
        fingerprinted_realdir)

      self.assert_success(self.run_pants_with_workdir([
        'compile',
        'export-classpath',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
        '--compile-zinc-debug-symbols',
        '--workdir-max-build-entries={}'.format(max_entries_per_target)
      ], workdir))

      # stable, current, and 2 newest dirs
      self.assertEqual(os.path.dirname(os.path.dirname(os.path.realpath(classpath))), target_dir_in_pantsd)
      new_cache_dir_fingerprinted = self.get_cache_subdir(target_dir_in_pantsd, other_dirs=newest_expected_dirs)
      # subsequent run with --compile-zinc-debug-symbols will invalidate previous build thus triggering the clean up.
      self.assertNotEqual(new_cache_dir_fingerprinted, remaining_cache_dir_fingerprinted)
      new_fingerprinted_realdir = os.path.realpath(os.path.join(target_dir_in_pantsd, 'current'))
      self.assertEqual(new_fingerprinted_realdir,
                       new_cache_dir_fingerprinted.rstrip('/'))
