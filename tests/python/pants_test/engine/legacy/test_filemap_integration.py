# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from os.path import abspath, join

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class FilemapIntegrationTest(PantsRunIntegrationTest):
  def test_testprojects(self):
    self.do_command(True, True, 'filemap', 'testprojects::')

  TEST_EXCLUDE_FILES = {'a.py', 'aa.py', 'aaa.py', 'ab.py', 'aabb.py',
                        'dir1/a.py', 'dir1/aa.py', 'dir1/aaa.py', 'dir1/ab.py', 'dir1/aabb.py',
                        'dir1/dirdir1/a.py', 'dir1/dirdir1/aa.py', 'dir1/dirdir1/ab.py'}

  def setUp(self):
    super(FilemapIntegrationTest, self).setUp()
    self.path_prefix = 'testprojects/tests/python/pants/file_sets/'
    project_tree = FileSystemProjectTree(abspath(self.path_prefix), ['BUILD', '.*'])
    scan_set = set()
    for root, dirs, files in project_tree.walk(''):
      scan_set.update({join(root, f) for f in files})

    self.assertEquals(scan_set, self.TEST_EXCLUDE_FILES)

  def _extract_exclude_output(self, test_name):
    stdout_data = self.do_command(True, True, 'filemap', '{}:{}'.format(self.path_prefix, test_name)).stdout_data
    return {s.split(' ')[0].replace(self.path_prefix, '')
            for s in stdout_data.split('\n') if s.startswith(self.path_prefix)}

  def test_exclude_string(self):
    test_out = self._extract_exclude_output('exclude_string')
    self.assertEquals(self.TEST_EXCLUDE_FILES - {'aaa.py', 'dir1/aaa.py'},
                      test_out)

  def test_exclude_globs(self):
    test_out = self._extract_exclude_output('exclude_globs')
    self.assertEquals(self.TEST_EXCLUDE_FILES - {'aabb.py', 'dir1/dirdir1/aa.py'},
                      test_out)

  def test_exclude_rglobs(self):
    test_out = self._extract_exclude_output('exclude_rglobs')
    self.assertEquals(self.TEST_EXCLUDE_FILES - {'ab.py', 'aabb.py', 'dir1/ab.py', 'dir1/aabb.py', 'dir1/dirdir1/ab.py'},
                      test_out)

  def test_exclude_zglobs(self):
    test_out = self._extract_exclude_output('exclude_zglobs')
    # TODO: ZGlobs.to_filespecs does not match files in the current directory when a pattern
    # starts with `**`; see: https://github.com/pantsbuild/pants/issues/3413
    self.assertEquals(self.TEST_EXCLUDE_FILES - {'dir1/ab.py', 'dir1/aabb.py', 'dir1/dirdir1/ab.py'},
                      test_out)

  def test_exclude_composite(self):
    test_out = self._extract_exclude_output('exclude_composite')
    # TODO: ZGlobs.to_filespecs does not match files in the current directory when a pattern
    # starts with `**`; see: https://github.com/pantsbuild/pants/issues/3413
    self.assertEquals(self.TEST_EXCLUDE_FILES -
                      {'aaa.py', 'dir1/a.py', 'dir1/dirdir1/a.py'},
                      test_out)
