# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir


class AnalysisTools(object):
  """Analysis manipulation methods required by JvmCompile."""
  _IVY_HOME_PLACEHOLDER = '/_IVY_HOME_PLACEHOLDER'
  _PANTS_HOME_PLACEHOLDER = '/_PANTS_HOME_PLACEHOLDER'

  def __init__(self, context, parser, analysis_cls):
    self.parser = parser
    self._java_home = context.java_home
    self._ivy_home = context.ivy_home
    self._pants_home = get_buildroot()
    self._analysis_cls = analysis_cls

  def split_to_paths(self, analysis_path, split_path_pairs, catchall_path=None):
    """Split an analysis file.

    split_path_pairs: A list of pairs (split, output_path) where split is a list of source files
    whose analysis is to be split out into output_path. The source files may either be
    absolute paths, or relative to the build root.

    If catchall_path is specified, the analysis for any sources not mentioned in the splits is
    split out to that path.
    """
    analysis = self.parser.parse_from_path(analysis_path)
    splits, output_paths = zip(*split_path_pairs)
    split_analyses = analysis.split(splits, catchall_path is not None)
    if catchall_path is not None:
      output_paths = output_paths + (catchall_path, )
    for analysis, path in zip(split_analyses, output_paths):
      analysis.write_to_path(path)

  def merge_from_paths(self, analysis_paths, merged_analysis_path):
    """Merge multiple analysis files into one."""
    analyses = [self.parser.parse_from_path(path) for path in analysis_paths]
    merged_analysis = self._analysis_cls.merge(analyses)
    merged_analysis.write_to_path(merged_analysis_path)

  def relativize(self, src_analysis, relativized_analysis):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file = os.path.join(tmp_analysis_dir, 'analysis.relativized')

      # NOTE: We can't port references to deps on the Java home. This is because different JVM
      # implementations on different systems have different structures, and there's not
      # necessarily a 1-1 mapping between Java jars on different systems. Instead we simply
      # drop those references from the analysis file.
      #
      # In practice the JVM changes rarely, and it should be fine to require a full rebuild
      # in those rare cases.
      rebasings = [
        (self._java_home, None),
        (self._ivy_home, self._IVY_HOME_PLACEHOLDER),
        (self._pants_home, self._PANTS_HOME_PLACEHOLDER),
        ]
      # Work on a tmpfile, for safety.
      self._rebase_from_path(src_analysis, tmp_analysis_file, rebasings)
      shutil.move(tmp_analysis_file, relativized_analysis)

  def localize(self, src_analysis, localized_analysis):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file = os.path.join(tmp_analysis_dir, 'analysis')
      rebasings = [
        (AnalysisTools._IVY_HOME_PLACEHOLDER, self._ivy_home),
        (AnalysisTools._PANTS_HOME_PLACEHOLDER, self._pants_home),
        ]
      # Work on a tmpfile, for safety.
      self._rebase_from_path(src_analysis, tmp_analysis_file, rebasings)
      shutil.move(tmp_analysis_file, localized_analysis)

  def _rebase_from_path(self, input_analysis_path, output_analysis_path, rebasings):
    """Rebase file paths in an analysis file.

    rebasings: A list of path prefix pairs [from_prefix, to_prefix] to rewrite.
               to_prefix may be None, in which case matching paths are removed entirely.
    """
    analysis = self.parser.parse_from_path(input_analysis_path)
    analysis.write_to_path(output_analysis_path, rebasings=rebasings)
