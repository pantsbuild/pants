# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import StringIO
import unittest

from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis import JMakeAnalysis
from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis_parser import JMakeAnalysisParser
from pants.util.contextutil import environment_as


class TestJmakeAnalysis(unittest.TestCase):
  def setUp(self):
    self.maxDiff = None

  def test_simple(self):
    def get_test_analysis_path(name):
      return os.path.join(os.path.dirname(__file__), 'testdata', 'simple', name)

    def get_analysis_text(name):
      with open(get_test_analysis_path(name), 'r') as fp:
        return fp.read()

    def parse_analyis(name):
      return JMakeAnalysisParser().parse_from_path(get_test_analysis_path(name))

    def analysis_to_string(analysis):
      buf = StringIO.StringIO()
      analysis.write(buf)
      return buf.getvalue()

    with environment_as(JMAKE_SORTED_ANALYSIS='1'):
      full_analysis = parse_analyis('simple.analysis')

      analysis_splits = full_analysis.split([
        [b'/src/pants/examples/src/java/org/pantsbuild/example/hello/greet/Greeting.java'],
        [b'/src/pants/examples/src/java/org/pantsbuild/example/hello/main/HelloMain.java'],
      ])
      self.assertEquals(len(analysis_splits), 2)

      def compare_split(i):
        expected_filename = 'simple_split{0}.analysis'.format(i)

        # First compare as objects.
        expected_analyis = parse_analyis(expected_filename)
        self.assertTrue(expected_analyis.is_equal_to(analysis_splits[i]))

        # Then compare as text.
        expected = get_analysis_text(expected_filename)
        actual = analysis_to_string(analysis_splits[i])
        self.assertMultiLineEqual(expected, actual)

      compare_split(0)
      compare_split(1)

      # Now merge and check that we get what we started with.
      merged_analysis = JMakeAnalysis.merge(analysis_splits)
      # Check that they compare as objects.
      self.assertTrue(full_analysis.is_equal_to(merged_analysis))
      # Check that they compare as text.
      expected = get_analysis_text('simple.analysis')
      actual = analysis_to_string(merged_analysis)
      self.assertMultiLineEqual(expected, actual)

      # Now check rebasing.
      orig = iter(get_analysis_text('simple.analysis').splitlines(True))
      expected_rebased = get_analysis_text('simple.rebased.analysis')
      buf = StringIO.StringIO()
      JMakeAnalysisParser().rebase(orig, buf, b'/src/pants', b'$PANTS_HOME')
      rebased = buf.getvalue()
      self.assertMultiLineEqual(expected_rebased, rebased)
