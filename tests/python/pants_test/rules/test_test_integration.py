# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestIntegrationTest(PantsRunIntegrationTest):

  def test_passing_python_test(self):
    args = [
      '--no-v1',
      '--v2',
      'test',
      'testprojects/tests/python/pants/dummies:passing_target',
    ]
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
    self.assertEqual("""I am a python test which passed

testprojects/tests/python/pants/dummies:passing_target                          .....   SUCCESS
""", pants_run.stdout_data)
    self.assertEqual("", pants_run.stderr_data)
    self.assertEqual(pants_run.returncode, 0)

  def test_failing_python_test(self):
    args = [
      '--no-v1',
      '--v2',
      'test',
      'testprojects/tests/python/pants/dummies:failing_target',
    ]
    pants_run = self.run_pants(args)
    self.assert_failure(pants_run)
    self.assertEqual("""I am a python test which failed

testprojects/tests/python/pants/dummies:failing_target                          .....   FAILURE
""", pants_run.stdout_data)
    self.assertEqual("", pants_run.stderr_data)
    self.assertEqual(pants_run.returncode, 1)

  def test_mixed_python_tests(self):
    args = [
      '--no-v1',
      '--v2',
      'test',
      'testprojects/tests/python/pants/dummies:failing_target',
      'testprojects/tests/python/pants/dummies:passing_target',
    ]
    pants_run = self.run_pants(args)
    self.assert_failure(pants_run)
    self.assertEqual("""I am a python test which failed
I am a python test which passed

testprojects/tests/python/pants/dummies:failing_target                          .....   FAILURE
testprojects/tests/python/pants/dummies:passing_target                          .....   SUCCESS
""", pants_run.stdout_data)
    self.assertEqual("", pants_run.stderr_data)
    self.assertEqual(pants_run.returncode, 1)
