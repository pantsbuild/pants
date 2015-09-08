# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir


class AnalysisTools(object):
  """Analysis manipulation methods required by JvmCompile."""
  # Note: The value string isn't the same as the symbolic name for legacy reasons:
  # We changed the name of the var, but didn't want to invalidate all cached artifacts just
  # for that reason.
  # TODO: If some future change requires us to invalidate all cached artifacts for some good reason
  # (by bumping GLOBAL_CACHE_KEY_GEN_VERSION), we can use that opportunity to change this string.
  _PANTS_HOME_PLACEHOLDER = b'/_PANTS_HOME_PLACEHOLDER'

  def __init__(self, java_home, parser, analysis_cls):
    self.parser = parser
    self._java_home = java_home
    self._pants_home = get_buildroot().encode('utf-8')
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
      # Work on a tmpfile, for safety.
      self.parser.rebase_from_path(src_analysis, tmp_analysis_file,
                                   self._pants_home, self._PANTS_HOME_PLACEHOLDER,
                                   self._java_home)
      shutil.move(tmp_analysis_file, relativized_analysis)

  def localize(self, src_analysis, localized_analysis):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file = os.path.join(tmp_analysis_dir, 'analysis')
      rebasings = [
        (AnalysisTools._PANTS_HOME_PLACEHOLDER, self._pants_home),
        ]
      # Work on a tmpfile, for safety.
      self.parser.rebase_from_path(src_analysis, tmp_analysis_file,
                                   self._PANTS_HOME_PLACEHOLDER, self._pants_home)
      shutil.move(tmp_analysis_file, localized_analysis)
