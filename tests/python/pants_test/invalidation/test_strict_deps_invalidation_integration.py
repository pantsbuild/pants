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

  @classmethod
  def hermetic(cls):
    return True

  def modify_transitive_deps_and_compile(self, target_name, invalidate_root_target_expected, *extra_args):
    with self.temporary_sourcedir() as tmp_src:
      src_dir = os.path.relpath(os.path.join(tmp_src, os.path.basename(self.TEST_SRC)), get_buildroot())
      shutil.copytree(self.TEST_SRC, src_dir)
      with self.temporary_workdir() as workdir:
        cmd = ['compile', '{}:{}'.format(src_dir, target_name)]
        cmd.extend(extra_args)
        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)

        with open(os.path.join(src_dir, 'D.java'), 'ab') as fh:
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
    # C1 depends on E, which is an alias target. E depends on D.
    # When D is changed, even though C1 has strict_deps set to True,
    # we expect C1 to be invalidated.
    self.modify_transitive_deps_and_compile('C1', True)

  def test_non_strict_deps_root_with_strict_deps_dependency(self):
    # A4 depends on B1 which has strict_deps set to True. However, since A4 has
    # strict_deps set to False, changing transitive deps of A4 should trigger
    # recompilation of A4.
    self.modify_transitive_deps_and_compile('A4', True)
