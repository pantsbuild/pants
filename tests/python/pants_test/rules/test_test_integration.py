# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestIntegrationTest(PantsRunIntegrationTest):

  # TODO: Modify flags (or pytest) so that output is hermetic and deterministic, and doesn't require fuzzy matching
  def assert_fuzzy_string_match(self, got, want):
    want_lines = want.split('\n')
    got_lines = got.split('\n')
    self.assertEqual(len(want_lines), len(got_lines), 'Wrong number of lines comparing:\nWANT:\n{}\nGOT:\n{}'.format(want, got))

    for line_number, (want_line, got_line) in enumerate(zip(want_lines, got_lines)):
      want_parts = want_line.split('SOME_TEXT')
      if len(want_parts) == 1:
        self.assertEqual(want_line, got_line, "Line {} wrong".format(line_number))
      elif len(want_parts) == 2:
        self.assertTrue(got_line.startswith(want_parts[0]), 'Line {} Want "{}" to start with "{}"'.format(line_number, got_line, want_parts[0]))
        self.assertTrue(got_line.endswith(want_parts[1]), 'Line {} Want "{}" to end with "{}"'.format(line_number, got_line, want_parts[1]))

  def test_passing_python_test(self):
    args = [
      '--no-v1',
      '--v2',
      'test',
      'testprojects/tests/python/pants/dummies:passing_target',
    ]
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

    self.assertEqual("", pants_run.stderr_data)
    self.assertEqual(pants_run.returncode, 0)

    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      """============================= test session starts ==============================
platform SOME_TEXT
rootdir: SOME_TEXT
collected 1 item

testprojects/tests/python/pants/dummies/test_pass.py .                   [100%]

=========================== 1 passed in SOME_TEXT ===========================

testprojects/tests/python/pants/dummies:passing_target                          .....   SUCCESS
""",
    )

  def test_failing_python_test(self):
    args = [
      '--no-v1',
      '--v2',
      'test',
      'testprojects/tests/python/pants/dummies:failing_target',
    ]
    pants_run = self.run_pants(args)
    self.assert_failure(pants_run)
    self.assertEqual("", pants_run.stderr_data)
    self.assertEqual(pants_run.returncode, 1)
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      """============================= test session starts ==============================
platform SOME_TEXT
rootdir: SOME_TEXT
collected 1 item

testprojects/tests/python/pants/dummies/test_fail.py F                   [100%]

=================================== FAILURES ===================================
__________________________________ test_fail ___________________________________

    def test_fail():
>     assert False
E     assert False

testprojects/tests/python/pants/dummies/test_fail.py:2: AssertionError
=========================== 1 failed in SOME_TEXT ===========================

testprojects/tests/python/pants/dummies:failing_target                          .....   FAILURE
""",
    )

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
    self.assertEqual("", pants_run.stderr_data)
    self.assertEqual(pants_run.returncode, 1)
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      """============================= test session starts ==============================
platform SOME_TEXT
rootdir: SOME_TEXT
collected 1 item

testprojects/tests/python/pants/dummies/test_fail.py F                   [100%]

=================================== FAILURES ===================================
__________________________________ test_fail ___________________________________

    def test_fail():
>     assert False
E     assert False

testprojects/tests/python/pants/dummies/test_fail.py:2: AssertionError
=========================== 1 failed in SOME_TEXT ===========================
============================= test session starts ==============================
platform SOME_TEXT
rootdir: SOME_TEXT
collected 1 item

testprojects/tests/python/pants/dummies/test_pass.py .                   [100%]

=========================== 1 passed in SOME_TEXT ===========================

testprojects/tests/python/pants/dummies:failing_target                          .....   FAILURE
testprojects/tests/python/pants/dummies:passing_target                          .....   SUCCESS
""",
    )
