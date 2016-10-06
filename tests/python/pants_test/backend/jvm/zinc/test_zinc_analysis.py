# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import StringIO
import unittest
import zipfile
from contextlib import contextmanager

from pants.backend.jvm.zinc.zinc_analysis_element import ZincAnalysisElement
from pants.backend.jvm.zinc.zinc_analysis_parser import ZincAnalysisParser
from pants.util.contextutil import Timer, environment_as, temporary_dir


# Setting this environment variable tells the test to generate new test data (see below).
_TEST_DATA_SOURCE_ENV_VAR = 'ZINC_ANALYSIS_TEST_DATA_SOURCE'


@contextmanager
def _temp_test_dir(zipfile_name):
  """Yields a test directory containing the files in the specified zipfile."""
  zipfile_path = os.path.join(os.path.dirname(__file__), 'testdata', zipfile_name)
  with temporary_dir() as tmpdir:
    zf = zipfile.ZipFile(zipfile_path, 'r')
    zf.extractall(tmpdir)
    yield tmpdir


class ZincAnalysisTestBase(unittest.TestCase):
  def setUp(self):
    self.maxDiff = None
    self.total_time = 0

  def _time(self, work, msg):
    with Timer() as timer:
      ret = work()
    elapsed = timer.elapsed
    print('%s in %f seconds.' % (msg, elapsed))
    self.total_time += elapsed
    return ret


class ZincAnalysisTestSimple(ZincAnalysisTestBase):

  # Test a simple example that is non-trivial, but still small enough to verify manually.
  def test_simple(self):
    with environment_as(ZINCUTILS_SORTED_ANALYSIS='1'):
      def get_test_analysis_path(name):
        return os.path.join(os.path.dirname(__file__), 'testdata', 'simple', name)

      def get_analysis_text(name):
        with open(get_test_analysis_path(name), 'r') as fp:
          return fp.read()

      # Now check rebasing.
      orig = iter(get_analysis_text('simple.analysis').splitlines(True))
      expected_rebased = get_analysis_text('simple.rebased.analysis')
      buf = StringIO.StringIO()
      ZincAnalysisParser().rebase(orig, buf, b'/src/pants', b'$PANTS_HOME')
      rebased = buf.getvalue()
      self.assertMultiLineEqual(expected_rebased, rebased)

      # And rebasing+filtering.
      orig = iter(get_analysis_text('simple.analysis').splitlines(True))
      expected_filtered_rebased = get_analysis_text('simple.rebased.filtered.analysis')
      buf = StringIO.StringIO()
      ZincAnalysisParser().rebase(orig, buf, b'/src/pants', b'$PANTS_HOME',
                                  b'/Library/Java/JavaVirtualMachines/jdk1.8.0_40.jdk')
      filtered_rebased = buf.getvalue()
      self.assertMultiLineEqual(expected_filtered_rebased, filtered_rebased)

      # Check parse_deps is returning both bin and src dependencies.
      infile = iter(get_analysis_text('simple.analysis').splitlines(True))
      deps = ZincAnalysisParser().parse_deps(infile, '')
      f = '/src/pants/examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala'
      self.assertItemsEqual(deps[f], [
          '/Library/Java/JavaVirtualMachines/jdk1.8.0_40.jdk/Contents/Home/jre/lib/rt.jar',
          '/src/pants/examples/src/scala/org/pantsbuild/example/hello/welcome/Welcome.scala',
        ])


class ZincAnalysisTestLarge(ZincAnalysisTestBase):

  # Test on a couple of large files, primarily for benchmarking.
  # Note that we don't set ZINCUTILS_SORTED_ANALYSIS='1', as we want to benchmark production
  # performance (without unnecessary sorting).
  def test_large(self):
    parser = ZincAnalysisParser()

    with _temp_test_dir('large.zip') as testdir:
      print('Operating in test dir: {}'.format(testdir))
      # Parse analysis files.
      analysis_file_names = [b'downstream.analysis', b'upstream.analysis']
      analysis_files = [os.path.join(testdir, f) for f in analysis_file_names]

      def msg(prefix):
        return '{0} [{1}]'.format(prefix, ', '.join(analysis_file_names))

      analyses = self._time(lambda: [parser.parse_from_path(f) for f in analysis_files],
                            msg('Parsed'))

      # Write them back out individually.
      writeout_dir = os.path.join(testdir, b'write')
      os.mkdir(writeout_dir)
      def write(file_name, analysis):
        outpath = os.path.join(writeout_dir, file_name)
        analysis.write_to_path(outpath)

      def _write_all():
        for analysis_file, analysis in zip(analysis_files, analyses):
          write(os.path.basename(analysis_file), analysis)

      self._time(_write_all, msg('Wrote'))

    print('Total time: %f seconds' % self.total_time)


class ZincAnalysisTestSorting(ZincAnalysisTestBase):
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
