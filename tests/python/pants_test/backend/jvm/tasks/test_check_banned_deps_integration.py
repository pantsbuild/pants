# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CheckBannedDepsTest(PantsRunIntegrationTest):

  TESTPROJECT_PATH = 'testprojects/src/scala/org/pantsbuild/testproject/banned_deps_test'

  def _in_testproject(self, target):
    return '{}:{}'.format(self.TESTPROJECT_PATH, target)

  def test_package_constraints(self):
    pants_run = self.do_command(
      '--no-compile-check-banned-deps-skip',
      'compile',
      self._in_testproject('ban_packages'),
      success=False)
    self.assertIn(
      'Target testprojects/src/scala bans package "scopt", which bans target 3rdparty/jvm with classes (',
      pants_run.stderr_data.strip())

  def test_test_dependency_constraints(self):
    pants_run = self.do_command(
      '--no-compile-check-banned-deps-skip',
      'compile',
      self._in_testproject('ban_testdeps'),
      success=False)
    self.assertIn(
      'Target testprojects/src/scala has test dependencies on target testprojects/src/scala',
      pants_run.stderr_data.strip())

  def test_tag_constraints(self):
    pants_run = self.do_command(
      '--no-compile-check-banned-deps-skip',
      'compile',
      self._in_testproject('ban_tags'),
      success=False)
    self.assertIn(
      'Target testprojects/src/scala has baned tag "deprecated", but these target has it testprojects/src/scala',
      pants_run.stderr_data.strip())
