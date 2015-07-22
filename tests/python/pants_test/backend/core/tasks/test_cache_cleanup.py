# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.java.java_compile import JavaCompile
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CacheCleanupTest(PantsRunIntegrationTest):

  def test_leave_one(self):
    """ Ensure that max-old of 1 removes all but one files"""

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, JavaCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main')

      touch(os.path.join(artifact_dir, 'old_cache_test1'))
      touch(os.path.join(artifact_dir, 'old_cache_test2'))
      touch(os.path.join(artifact_dir, 'old_cache_test3'))
      touch(os.path.join(artifact_dir, 'old_cache_test4'))
      touch(os.path.join(artifact_dir, 'old_cache_test5'))

      config = {'cache.compile.java': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(['compile.java',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-target-entry-max=1',],
                                 config=config)
      self.assert_success(pants_run)

      # One artifact for java 6 and one old cache file

      self.assertEqual(len(os.listdir(artifact_dir)), 2)

      # Rerun for java 7
      pants_run = self.run_pants(['compile.java',
                                  '--target=1.7',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-target-entry-max=1'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 6 (old cache file) and one for 7
      self.assertEqual(len(os.listdir(artifact_dir)), 2)

  def test_leave_none(self):
    """ Ensure that max-old of zero removes all files

    This test should ensure that conditional doesn't change to the simpler test of if max_old since
    we need to handle zero as well.
    """

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, JavaCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main')

      touch(os.path.join(artifact_dir, 'old_cache_test1'))
      touch(os.path.join(artifact_dir, 'old_cache_test2'))
      touch(os.path.join(artifact_dir, 'old_cache_test3'))
      touch(os.path.join(artifact_dir, 'old_cache_test4'))
      touch(os.path.join(artifact_dir, 'old_cache_test5'))

      config = {'cache.compile.java': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(['compile.java',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-target-entry-max=0',],
                                 config=config)
      self.assert_success(pants_run)

      # One artifact for java 6 and one old cache file

      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for java 7
      pants_run = self.run_pants(['compile.java',
                                  '--target=1.7',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
                                  '--cache-target-entry-max=0'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 6 (old cache file) and one for 7
      self.assertEqual(len(os.listdir(artifact_dir)), 1)
