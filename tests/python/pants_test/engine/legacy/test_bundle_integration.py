# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class BundleIntegrationTest(PantsRunIntegrationTest):

  TARGET_PATH = 'testprojects/src/java/org/pantsbuild/testproject/bundle'

  def test_bundle_basic(self):
    args = ['-q', 'bundle', self.TARGET_PATH]
    self.do_command(*args, success=True, enable_v2_engine=True)

  @ensure_engine
  def test_bundle_mapper(self):
    with temporary_dir() as temp_distdir:
      with self.pants_results(
          ['-q',
           '--pants-distdir={}'.format(temp_distdir),
           'bundle',
           '{}:mapper'.format(self.TARGET_PATH)]) as pants_run:
        self.assert_success(pants_run)
        self.assertTrue(os.path.isfile(
          '{}/{}.mapper-bundle/bundle_files/file1.txt'.format(temp_distdir, self.TARGET_PATH.replace('/', '.'))))

  @ensure_engine
  def test_bundle_relative_to(self):
    with temporary_dir() as temp_distdir:
      with self.pants_results(
        ['-q',
          '--pants-distdir={}'.format(temp_distdir),
          'bundle',
          '{}:relative_to'.format(self.TARGET_PATH)]) as pants_run:
        self.assert_success(pants_run)
        self.assertTrue(os.path.isfile(
          '{}/{}.relative_to-bundle/b/file1.txt'.format(temp_distdir, self.TARGET_PATH.replace('/', '.'))))

  @ensure_engine
  def test_bundle_rel_path(self):
    with temporary_dir() as temp_distdir:
      with self.pants_results(
        ['-q',
          '--pants-distdir={}'.format(temp_distdir),
          'bundle',
          '{}:rel_path'.format(self.TARGET_PATH)]) as pants_run:
        self.assert_success(pants_run)
        self.assertTrue(os.path.isfile(
          '{}/{}.rel_path-bundle/b/file1.txt'.format(temp_distdir, self.TARGET_PATH.replace('/', '.'))))

  @ensure_engine
  def test_bundle_resource_ordering(self):
    """Ensures that `resources=` ordering is respected."""
    pants_run = self.run_pants(
      ['-q',
       'run',
       'testprojects/src/java/org/pantsbuild/testproject/bundle:bundle-resource-ordering']
    )
    self.assert_success(pants_run)
    self.assertEquals(pants_run.stdout_data, 'Hello world from Foo\n\n')
