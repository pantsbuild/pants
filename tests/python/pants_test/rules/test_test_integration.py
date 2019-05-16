# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestIntegrationTest(PantsRunIntegrationTest):

  def run_pants(self, trailing_args):
    args = [
      '--no-v1',
      '--v2',
      '--no-colors',
      '--level=warn',
      'test',
    ] + trailing_args
    # Set TERM=dumb to stop pytest from trying to be clever and wrap lines which may interfere with
    # our golden data.
    return super(TestIntegrationTest, self).run_pants(args, extra_env={'TERM': 'dumb'})

  # TODO: Modify flags (or pytest) so that output is hermetic and deterministic, and doesn't require fuzzy matching
  def assert_fuzzy_string_match(self, got, want):
    want_lines = want.split('\n')
    got_lines = got.split('\n')
    self.assertEqual(len(want_lines), len(got_lines), 'Wrong number of lines comparing:\nWANT:\n{}\nGOT:\n{}'.format(want, got))

    for line_number, (want_line, got_line) in enumerate(zip(want_lines, got_lines)):
      want_parts = want_line.split('SOME_TEXT')
      if len(want_parts) == 1:
        self.assertEqual(want_line, got_line,
                         "Line {} wrong: want '{}', got '{}'"
                         .format(line_number, want_line, got_line))
      elif len(want_parts) == 2:
        self.assertTrue(got_line.startswith(want_parts[0]), 'Line {} Want "{}" to start with "{}"'.format(line_number, got_line, want_parts[0]))
        self.assertTrue(got_line.endswith(want_parts[1]), 'Line {} Want "{}" to end with "{}"'.format(line_number, got_line, want_parts[1]))

  def run_passing_pants_test(self, trailing_args):
    pants_run = self.run_pants(trailing_args)
    self.assert_success(pants_run)
    return pants_run

  def run_failing_pants_test(self, trailing_args):
    pants_run = self.run_pants(trailing_args)
    self.assert_failure(pants_run)
    self.assertEqual('Tests failed\n', pants_run.stderr_data)

    return pants_run

  def test_passing_python_test(self):
    pants_run = self.run_passing_pants_test([
      'testprojects/tests/python/pants/dummies:passing_target',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:passing_target stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_pass.py .                                             [100%]

        =========================== 1 passed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:passing_target                          .....   SUCCESS
        """),
    )

  def test_failing_python_test(self):
    pants_run = self.run_failing_pants_test([
      'testprojects/tests/python/pants/dummies:failing_target',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:failing_target stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_fail.py F                                             [100%]

        =================================== FAILURES ===================================
        __________________________________ test_fail ___________________________________

            def test_fail():
        >     assert False
        E     assert False

        pants/dummies/test_fail.py:2: AssertionError
        =========================== 1 failed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:failing_target                          .....   FAILURE
        """),
    )

  def test_source_dep_absolute_import(self):
    pants_run = self.run_passing_pants_test([
      'testprojects/tests/python/pants/dummies:target_with_source_dep_absolute_import',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:target_with_source_dep_absolute_import stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_with_source_dep_absolute_import.py .                  [100%]

        =========================== 1 passed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:target_with_source_dep_absolute_import  .....   SUCCESS
        """)
      )

  def test_source_dep_relative_import(self):
    pants_run = self.run_passing_pants_test([
      'testprojects/tests/python/pants/dummies:target_with_source_dep_relative_import',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:target_with_source_dep_relative_import stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_with_source_dep_relative_import.py .                  [100%]

        =========================== 1 passed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:target_with_source_dep_relative_import  .....   SUCCESS
        """)
      )

  def test_thirdparty_dep(self):
    pants_run = self.run_passing_pants_test([
      'testprojects/tests/python/pants/dummies:target_with_thirdparty_dep',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:target_with_thirdparty_dep stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_with_thirdparty_dep.py .                              [100%]

        =========================== 1 passed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:target_with_thirdparty_dep              .....   SUCCESS
        """)
    )

  def test_transitive_dep(self):
    pants_run = self.run_passing_pants_test([
      'testprojects/tests/python/pants/dummies:target_with_transitive_dep',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:target_with_transitive_dep stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_with_transitive_dep.py .                              [100%]

        =========================== 1 passed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:target_with_transitive_dep              .....   SUCCESS
        """)
    )

  def test_mixed_python_tests(self):
    pants_run = self.run_failing_pants_test([
      'testprojects/tests/python/pants/dummies:failing_target',
      'testprojects/tests/python/pants/dummies:passing_target',
    ])
    self.assert_fuzzy_string_match(
      pants_run.stdout_data,
      dedent("""\
        testprojects/tests/python/pants/dummies:failing_target stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_fail.py F                                             [100%]

        =================================== FAILURES ===================================
        __________________________________ test_fail ___________________________________

            def test_fail():
        >     assert False
        E     assert False

        pants/dummies/test_fail.py:2: AssertionError
        =========================== 1 failed in SOME_TEXT ===========================

        testprojects/tests/python/pants/dummies:passing_target stdout:
        ============================= test session starts ==============================
        platform SOME_TEXT
        rootdir: SOME_TEXT
        plugins: SOME_TEXT
        collected 1 item

        pants/dummies/test_pass.py .                                             [100%]

        =========================== 1 passed in SOME_TEXT ===========================


        testprojects/tests/python/pants/dummies:failing_target                          .....   FAILURE
        testprojects/tests/python/pants/dummies:passing_target                          .....   SUCCESS
        """),
    )
