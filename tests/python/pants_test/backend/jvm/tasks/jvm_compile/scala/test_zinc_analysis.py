# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import StringIO
import unittest

from pants.backend.jvm.tasks.jvm_compile.analysis_parser import ParseError
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.util.contextutil import Timer, temporary_dir
from pants.util.dirutil import safe_rmtree


# Setting this environment variable tells the test to generate new test data (see below).
_TEST_DATA_SOURCE_ENV_VAR = 'ZINC_ANALYSIS_TEST_DATA_SOURCE'


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
      return os.path.join(os.path.dirname(__file__), 'testdata', 'simple', name)

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
      ['/src/pants/examples/src/scala/org/pantsbuild/example/hello/welcome/Welcome.scala'],
      ['/src/pants/examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala'],
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
    if os.environ.get(_TEST_DATA_SOURCE_ENV_VAR):
      print('\n>>>>>>>>> {} set: skipping test, generating canonical test data instead.'.format(
        _TEST_DATA_SOURCE_ENV_VAR))
      self._generate_testworthy_splits()
      return

    parser = ZincAnalysisParser()

    with temporary_dir() as tmpdir:
      analysis_dir = os.path.join(os.path.dirname(__file__), 'testdata', 'complex')

      # Parse analysis files.
      analysis_files = [os.path.join(analysis_dir, f)
                        for f in os.listdir(analysis_dir) if f.endswith('.analysis')]
      num_analyses = len(analysis_files)

      def parse(f):
        return parser.parse_from_path(f)

      analyses = self._time(lambda: [parse(f) for f in analysis_files],
                            'Parsed %d files' % num_analyses)

      # Get the right exception on a busted file.
      truncated_dir = os.path.join(tmpdir, 'truncated')
      os.mkdir(truncated_dir)
      f = os.path.join(truncated_dir, os.path.basename(analysis_files[0]))
      shutil.copy(analysis_files[0], f)
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

      # Read the expected merged analysis from file.
      expected_merged_analysis_path = os.path.join(analysis_dir, 'all.analysis.merged')
      expected_merged_analysis = self._time(
        lambda: parser.parse_from_path(expected_merged_analysis_path),
        'Read expected merged analysis from %s' % expected_merged_analysis_path)

      # Compare the merge result with the re-read one.
      diffs = merged_analysis.diff(merged_analysis2)
      self.assertEquals(merged_analysis, merged_analysis2, ''.join(
        [unicode(diff) for diff in diffs]))

      # Compare the merge result with the expected.
      diffs = expected_merged_analysis.diff(merged_analysis2)
      self.assertEquals(expected_merged_analysis, merged_analysis2, ''.join(
        [unicode(diff) for diff in diffs]))

      # Split the merged analysis back to individual analyses.
      sources_per_analysis = [a.stamps.sources.keys() for a in analyses]
      split_analyses = self._time(lambda: merged_analysis2.split(
        sources_per_analysis, catchall=True), 'Split back into %d analyses' % num_analyses)

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
        # Note that it's not true in general that merging splits and then splitting them back out
        # should yield the exact same analysis. Some small differences can happen. For example:
        # splitA may have an external src->class on a class from a source file in splitB; When
        # merging, that becomes a src->src dependency; And when splitting back out that src
        # dependency becomes a dependency on a representative class, which may not be
        # the original class SplitA depended on.
        #
        # This comparison works here only because we've taken care to prepare test data for which
        # it should hold. See _generate_testworthy_splits below for how to do so.
        self.assertEquals(analysis, split_analysis, ''.join([unicode(diff) for diff in diffs]))

    print('Total time: %f seconds' % self.total_time)


  def _generate_testworthy_splits(self):
    """Take some non-canonical analysis files and generate test data from them.

    The resulting files will be "canonical". That is, merging and re-splitting them will yield
    the same files. Therefore the resulting files can be used as test data (after eyeballing them
    to ensure no pathologies).

    An easy way to generate input for this function is to run a scala compile on some targets using
    --strategy=isolated. Then .pants.d/compile/jvm/scala/isolated-analysis/ will contain a bunch
    of per-target analysis files.

    Those files can be anonymized (see anonymize_analysis.py), ideally with some non-ASCII words
    thrown in (as explained there), and then you can point this function to those anonymized
    files by setting ZINC_ANALYSIS_TEST_DATA_SOURCE=<dir> in the environment and running this test.

    Note: Yes, it's slightly problematic that we're using the very code we're testing to generate
    the test inputs. Hence the need to spot-check for obvious pathologies.
    """
    original_splits_dir = os.environ.get(_TEST_DATA_SOURCE_ENV_VAR)

    canonical_dir = os.path.join(original_splits_dir, 'canonical')
    safe_rmtree(canonical_dir)
    os.mkdir(canonical_dir)

    original_split_filenames = [f.decode('utf-8') for f in os.listdir(original_splits_dir)]
    original_splits_files = [os.path.join(original_splits_dir, f)
                             for f in original_split_filenames if f.endswith('.analysis')]

    parser = ZincAnalysisParser()
    original_split_analyses = [parser.parse_from_path(f) for f in original_splits_files]
    merged_analysis = ZincAnalysis.merge(original_split_analyses)
    merged_analysis.write_to_path(os.path.join(canonical_dir, 'all.analysis.merged'))

    # Split the merged analysis back to individual analyses.
    sources_per_analysis = [a.stamps.sources.keys() for a in original_split_analyses]
    split_analyses = merged_analysis.split(sources_per_analysis)
    for original_split_file, split_analysis in zip(original_splits_files, split_analyses):
      outpath = os.path.join(canonical_dir, os.path.basename(original_split_file))
      split_analysis.write_to_path(outpath)

    print('Wrote canonical analysis data to {}'.format(canonical_dir))
