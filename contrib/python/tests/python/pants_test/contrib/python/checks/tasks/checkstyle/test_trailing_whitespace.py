# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.trailing_whitespace import TrailingWhitespace


class TrailingWhitespaceTest(CheckstylePluginTestBase):
  plugin_type = TrailingWhitespace

  def test_exception_map(self):
    for test_input, results in [
      ([9,0,0], False),
      ([3,0,1], False),
      ([3,17,17], False),
      ([3,18,18], True),
      ([3,18,10000], True),  # """ continued strings have no ends
      ([6,8,8], False),
      ([6,19,19], True),
      ([6,19,23], True),
      ([6,23,25], False),  # ("  " continued have string termination
    ]:
      tw = self.get_plugin("""
      test_string_001 = ""
      test_string_002 = " "
      test_string_003 = \"\"\"
        foo{}
      \"\"\"
      test_string_006 = ("   "
                         "   ")
      class Foo(object):
        pass
      # comment 010
      test_string_011 = ''
      # comment 012
      # comment 013
      """.format('   '))  # Add the trailing whitespace with format, so that IDEs don't remove it.
      self.assertEqual(0, len(list(tw.nits())))
      self.assertEqual(results, bool(tw.has_exception(*test_input)))

  def test_continuation_with_exception(self):
    statement = """
    test_string_001 = ("   "{}
                       "   ")
    """.format('  ')  # Add the trailing whitespace with format, so that IDEs don't remove it.
    self.assertNit(statement, 'T200')

  def test_trailing_slash(self):
    statement = """
    foo = \\
      123
    bar = \"\"\"
      bin/bash foo \\
               bar \\
               baz
    \"\"\"
    """
    self.assertNit(statement, 'T201', expected_line_number=1)
