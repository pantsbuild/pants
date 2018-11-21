# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CheckBannedDepsIntegration(PantsRunIntegrationTest):

  TESTPROJECT_PATH = 'testprojects/src/scala/org/pantsbuild/testproject/banned_deps'

  def _in_testproject(self, target):
    return '{}{}'.format(self.TESTPROJECT_PATH, target)

  def compile_with_constraints(self, path_to_target, failure_message, success=True):
    pants_run = self.do_command(
      '--no-compile-check-banned-deps-skip',
      'compile',
      self._in_testproject(path_to_target),
      success=success
    )
    if not success:
      assert failure_message, "If you expect the run to fail, you should specify a failure_message"
      self.assertIn(
        failure_message,
        pants_run.stderr_data.strip())

  def test_package_constraints(self):
    self.compile_with_constraints(
      ':ban_packages',
      success=False,
      failure_message='ERROR!'
    )

  def test_test_dependency_constraints(self):
    self.compile_with_constraints(
      ':ban_testdeps',
      success=False,
      failure_message='ERROR!'
    )

  def test_tag_constraints(self):
    self.compile_with_constraints(
      ':ban_tag',
      success=False,
      failure_message='ERROR!'
    )

  def test_target_name(self):
    self.compile_with_constraints(
      ':ban_target_name',
      success=False,
      failure_message='ERROR!'
    )
