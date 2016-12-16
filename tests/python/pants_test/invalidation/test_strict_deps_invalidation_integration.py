# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class RunTrackerIntegrationTest(PantsRunIntegrationTest):

  TEST_SRC = 'testprojects/tests/java/org/pantsbuild/testproject/strictdeps'

  def copy_src_and_run_test(self, target_name, match_str):
    with self.temporary_sourcedir() as tmp_src:
      src_dir = os.path.relpath(os.path.join(tmp_src, os.path.basename(self.TEST_SRC)), get_buildroot())
      shutil.copytree(self.TEST_SRC, src_dir)
      with self.temporary_workdir() as workdir:
        cmd = ['compile', '{}:{}'.format(src_dir, target_name)]
        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)

        with open(os.path.join(src_dir, 'C.java'), 'ab') as fh:
          fh.write('\n')

        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)
        self.assertEqual(
          '{}:{}'.format(src_dir, target_name) in pants_run.stdout_data,
          match_str)

  def test_strict_deps_false(self):
    self.copy_src_and_run_test('A2', True)

  def test_strict_deps_true(self):
    self.copy_src_and_run_test('A1', False)
