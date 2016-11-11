# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import StringIO
import unittest

from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.zinc.zinc_analysis_element import ZincAnalysisElement
from pants.backend.jvm.zinc.zinc_analysis_parser import ZincAnalysisParser
from pants.util.contextutil import environment_as


class ZincAnalysisTestSimple(unittest.TestCase):

  # Test a simple example that is non-trivial, but still small enough to verify manually.
  def test_simple(self):
    with environment_as(ZINCUTILS_SORTED_ANALYSIS='1'):
      def get_test_analysis_path(name):
        return os.path.join(os.path.dirname(__file__), 'testdata', 'simple', name)

      def get_analysis_text(name):
        with open(get_test_analysis_path(name), 'r') as fp:
          return fp.read()

      def rebase(analysis_file, java_home=None):
        orig = get_analysis_text(analysis_file)
        buf = StringIO.StringIO()
        ZincAnalysisParser().rebase(iter(orig.splitlines(True)), buf,
                                    {b'/src/pants': AnalysisTools._PANTS_BUILDROOT_PLACEHOLDER,
                                     b'/src/pants/.pants.d': AnalysisTools._PANTS_WORKDIR_PLACEHOLDER}, java_home)
        return buf.getvalue()

      # Now check rebasing.
      rebased = rebase('simple.analysis')
      expected_rebased = get_analysis_text('simple.rebased.analysis')
      self.assertMultiLineEqual(expected_rebased, rebased)

      # And rebasing+filtering.
      rebased = rebase('simple.analysis', b'/Library/Java/JavaVirtualMachines/jdk1.8.0_40.jdk')
      expected_filtered_rebased = get_analysis_text('simple.rebased.filtered.analysis')
      self.assertMultiLineEqual(expected_filtered_rebased, rebased)

      # Check parse_deps is returning both bin and src dependencies.
      infile = iter(get_analysis_text('simple.analysis').splitlines(True))
      deps = ZincAnalysisParser().parse_deps(infile, '')
      self.assertItemsEqual(deps['/src/pants/examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala'], [
          '/Library/Java/JavaVirtualMachines/jdk1.8.0_40.jdk/Contents/Home/jre/lib/rt.jar',
          'org/pantsbuild/example/hello/welcome/WelcomeEverybody$.class',
        ])


class ZincAnalysisTestSorting(unittest.TestCase):
  class FakeElement(ZincAnalysisElement):
    headers = ('foo', )

  def test_sort(self):
    unsorted_arg = { '{}'.format(n): ['f1', 'f2', 'f0'] for n in range(9, -1, -1) }
    expected = ('foo:\n30 items\n' +
                ''.join('{n} -> f0\n{n} -> f1\n{n} -> f2\n'.format(n=n) for n in range(0, 10)))

    def do_test(elem):
      # The values of a single key should be sorted in memory.
      for n in range(0, 9):
        self.assertEquals(['f0', 'f1', 'f2'], elem.args[0]['{}'.format(n)])
      # And the keys themselves (and their values) should be sorted when writing.
      buf = StringIO.StringIO()
      elem.write(buf)
      output = buf.getvalue()
      self.assertMultiLineEqual(expected, output)

    always_sorted_elem = self.FakeElement([unsorted_arg], always_sort=True)
    do_test(always_sorted_elem)

    # Unsorted elements must still sort if the environment var is set.
    with environment_as(ZINCUTILS_SORTED_ANALYSIS='1'):
      unsorted_elem = self.FakeElement([unsorted_arg])
      do_test(unsorted_elem)
