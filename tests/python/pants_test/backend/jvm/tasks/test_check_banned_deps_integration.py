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
      '/constraint_impl_checks:ban_packages',
      success=False,
      failure_message='Target testprojects/src/scala bans package "scopt", which bans target 3rdparty/jvm with classes ('
    )

  def test_test_dependency_constraints(self):
    self.compile_with_constraints(
      '/constraint_impl_checks:ban_testdeps',
      success=False,
      failure_message='Target testprojects/src/scala has test dependencies on target testprojects/src/scala'
    )

  def test_tag_constraints(self):
    self.compile_with_constraints(
      '/constraint_impl_checks:ban_tags',
      success=False,
      failure_message='Target testprojects/src/scala has baned tag "deprecated", but these target has it testprojects/src/scala'
    )

  def test_graph_walk(self):
    self.compile_with_constraints(
      '/graph_walk/T:T',
      success=False,
      failure_message='Target testprojects/src/scala has baned tag "deprecated", but these target has it testprojects/src/scala'
    )
