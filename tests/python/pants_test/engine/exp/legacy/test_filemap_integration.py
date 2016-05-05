# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class FilemapIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
  def do_filemap(self, success, *args):
    args = ['run', 'src/python/pants/engine/exp/legacy:filemap', '--'] + list(args)
    pants_run = self.run_pants(args)
    if success:
      self.assert_success(pants_run)
    else:
      self.assert_failure(pants_run)
    return pants_run

  def test_scala_examples(self):
    self.do_filemap(True, 'examples/src/scala/org/pantsbuild/example/::')

  TEST_EXCLUDE_FILES = {'a.py', 'aa.py', 'aaa.py', 'ab.py', 'aabb.py',
                        'dir1/a.py', 'dir1/aa.py', 'dir1/aaa.py', 'dir1/ab.py', 'dir1/aabb.py',
                        'dir1/dirdir1/a.py', 'dir1/dirdir1/aa.py', 'dir1/dirdir1/ab.py'}

  def _extract_exclude_output(self, test_name):
    path_prefix = 'testprojects/tests/python/pants/file_sets/'
    stdout_data = self.do_filemap(True, '{}:{}'.format(path_prefix, test_name)).stdout_data
    return {s.split(' ')[0].replace(path_prefix, '')
            for s in stdout_data.split('\n') if s.startswith(path_prefix)}

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
    self.assertEquals(self.TEST_EXCLUDE_FILES - {'dir1/ab.py', 'dir1/aabb.py', 'dir1/dirdir1/ab.py'},
                      test_out)

  def test_exclude_nested(self):
    test_out = self._extract_exclude_output('exclude_nested')
    self.assertEquals(self.TEST_EXCLUDE_FILES - {'ab.py', 'dir1/dirdir1/ab.py'},
                      test_out)

  def test_exclude_composite(self):
    test_out = self._extract_exclude_output('exclude_composite')
    self.assertEquals(self.TEST_EXCLUDE_FILES -
                      {'aaa.py', 'ab.py', 'dir1/a.py', 'dir1/ab.py', 'dir1/dirdir1/a.py', 'dir1/dirdir1/ab.py'},
                      test_out)
