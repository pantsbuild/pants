# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import contextlib
import os
import StringIO
import tarfile
import unittest

from pants.backend.jvm.tasks.jvm_compile.analysis_parser import ParseError
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.util.contextutil import Timer, temporary_dir


class ZincAnalysisTest(unittest.TestCase):
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

  # Test a simple example that is non-trivial, but still small enough to verify manually.
  def test_split_merge(self):
    def get_test_analysis_path(name):
      return os.path.join(os.path.dirname(__file__), 'testdata', name)

    def get_analysis_text(name):
      with open(get_test_analysis_path(name), 'r') as fp:
        return fp.read()

    def parse_analyis(name):
      return ZincAnalysisParser().parse_from_path(get_test_analysis_path(name))

    def analysis_to_string(analysis):
      buf = StringIO.StringIO()
      analysis.write(buf)
      return buf.getvalue()

    full_analysis = parse_analyis('simple_analysis')

    analysis_splits = full_analysis.split([
      ['/src/pants/examples/src/scala/com/pants/example/hello/welcome/Welcome.scala'],
      ['/src/pants/examples/src/scala/com/pants/example/hello/exe/Exe.scala'],
    ])
    self.assertEquals(len(analysis_splits), 2)

    def compare_split(i):
      expected_filename = 'simple_analysis_split{0}'.format(i)

      # First compare as objects.  This verifies that __eq__ works, but is weaker than the
      # text comparison because in some cases there can be small text differences that don't
      # affect logical equivalence.
      expected_analyis = parse_analyis(expected_filename)
      self.assertTrue(expected_analyis == analysis_splits[i])

      # Then compare as text.  In this simple case we expect them to be byte-for-byte equal.
      expected = get_analysis_text(expected_filename)
      actual = analysis_to_string(analysis_splits[i])
      self.assertMultiLineEqual(expected, actual)

    compare_split(0)
    compare_split(1)

    # Now merge and check that we get what we started with.
    merged_analysis = ZincAnalysis.merge(analysis_splits)
    # Check that they compare as objects.
    self.assertTrue(full_analysis == merged_analysis)
    # Check that they compare as text.
    expected = get_analysis_text('simple_analysis')
    actual = analysis_to_string(merged_analysis)
    self.assertMultiLineEqual(expected, actual)


  # Test on large-scale analysis files.
  def test_analysis_files(self):
    parser = ZincAnalysisParser()

    with temporary_dir() as tmpdir:
      # Extract analysis files from tarball.
      analysis_tarball = os.path.join(os.path.dirname(__file__), 'testdata', 'analysis.tar.bz2')
      analysis_dir = os.path.join(tmpdir, 'orig')
      print('Extracting %s to %s' % (analysis_tarball, analysis_dir))
      os.mkdir(analysis_dir)
      with contextlib.closing(tarfile.open(analysis_tarball, 'r:bz2')) as tar:
        tar.extractall(analysis_dir)

      # Parse them.
      analysis_files = [os.path.join(analysis_dir, f)
                        for f in os.listdir(analysis_dir) if f.endswith('.analysis')]
      num_analyses = len(analysis_files)

      def parse(f):
        return parser.parse_from_path(f)

      analyses = self._time(lambda: [parse(f) for f in analysis_files],
                            'Parsed %d files' % num_analyses)

      # Get the right exception on a busted file
      f = analysis_files[0]
      with open(f, 'r+b') as truncated:
        truncated.seek(-150, os.SEEK_END)
        truncated.truncate()
      with self.assertRaises(ParseError):
        parse(f)

      # Write them back out individually.
      writeout_dir = os.path.join(tmpdir, 'write')
      os.mkdir(writeout_dir)
      def write(file_name, analysis):
        outpath = os.path.join(writeout_dir, file_name)
        analysis.write_to_path(outpath)

      def _write_all():
        for analysis_file, analysis in zip(analysis_files, analyses):
          write(os.path.basename(analysis_file), analysis)

      self._time(_write_all, 'Wrote %d files' % num_analyses)

      # Merge them.
      merged_analysis = self._time(lambda: ZincAnalysis.merge(analyses),
                                   'Merged %d files' % num_analyses)

      # Write merged analysis to file.
      merged_analysis_path = os.path.join(tmpdir, 'analysis.merged')
      self._time(lambda: merged_analysis.write_to_path(merged_analysis_path),
                 'Wrote merged analysis to %s' % merged_analysis_path)

      # Read merged analysis from file.
      merged_analysis2 = self._time(lambda: parser.parse_from_path(merged_analysis_path),
                                    'Read merged analysis from %s' % merged_analysis_path)

      # Split the merged analysis back to individual analyses.
      sources_per_analysis = [a.stamps.sources.keys() for a in analyses]
      split_analyses = self._time(lambda: merged_analysis2.split(sources_per_analysis, catchall=True),
                                  'Split back into %d analyses' % num_analyses)

      self.assertEquals(num_analyses + 1, len(split_analyses))  # +1 for the catchall.
      catchall_analysis = split_analyses[-1]

      # We expect an empty catchall.
      self.assertEquals(0, len(catchall_analysis.stamps.sources))

      # Diff the original analyses and the split ones.

      # Write the split to the tmpdir, for ease of debugging on failure.
      splits_dir = os.path.join(tmpdir, 'splits')
      os.mkdir(splits_dir)
      for analysis_file, analysis, split_analysis in zip(analysis_files, analyses, split_analyses):
        outfile_path = os.path.join(splits_dir, os.path.basename(analysis_file))
        split_analysis.write_to_path(outfile_path)
        diffs = analysis.diff(split_analysis)
        self.assertEquals(analysis, split_analysis, ''.join([str(diff) for diff in diffs]))

    print('Total time: %f seconds' % self.total_time)
