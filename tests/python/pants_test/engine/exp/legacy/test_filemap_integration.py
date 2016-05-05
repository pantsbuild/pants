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

  def test_exclude_files(self):
    path_prefix = 'testprojects/tests/python/pants/file_sets/'
    stdout_data = self.do_filemap(True, path_prefix + '::').stdout_data
    test_out = {s.split(' ')[0].replace(path_prefix, '')
                for s in stdout_data.split('\n') if s.startswith(path_prefix)}

    self.assertEquals({'a.py', 'aa.py', 'aabb.py',
                       'dir1/aa.py', 'dir1/ab.py', 'dir1/aabb.py',
                       'dir1/dirdir1/aa.py'
                       }, test_out)
