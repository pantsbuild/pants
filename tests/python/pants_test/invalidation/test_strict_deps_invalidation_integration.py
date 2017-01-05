# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class StrictDepsInvalidationIntegrationTest(PantsRunIntegrationTest):

  TEST_SRC = 'testprojects/tests/java/org/pantsbuild/testproject/strictdeps'

  def modify_transitive_deps_and_compile(self, target_name, invalidate_root_target_expected, *extra_args):
    with self.temporary_sourcedir() as tmp_src:
      src_dir = os.path.relpath(os.path.join(tmp_src, os.path.basename(self.TEST_SRC)), get_buildroot())
      shutil.copytree(self.TEST_SRC, src_dir)
      with self.temporary_workdir() as workdir:
        cmd = ['compile', '{}:{}'.format(src_dir, target_name)]
        cmd.extend(extra_args)
        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)

        with open(os.path.join(src_dir, 'C.java'), 'ab') as fh:
          fh.write('\n')

        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)
        self.assertEqual(
          '{}:{}'.format(src_dir, target_name) in pants_run.stdout_data,
          invalidate_root_target_expected)

  def test_strict_deps_false(self):
    self.modify_transitive_deps_and_compile('A2', True)

  def test_strict_deps_true(self):
    self.modify_transitive_deps_and_compile('A1', False)

  def test_strict_deps_global_true(self):
    self.modify_transitive_deps_and_compile('A3', False, '--java-strict-deps=True')

  def test_strict_deps_global_false(self):
    self.modify_transitive_deps_and_compile('A3', True, '--java-strict-deps=False')

  def test_strict_deps_alias_target(self):
    # B1 depends on D, which is an alias target. D depends on C.
    # When C is changed, even though B1 has strict_deps set to True,
    # we expect B1 to be invalidated.
    self.modify_transitive_deps_and_compile('B1', True)
