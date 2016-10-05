# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.util.contextutil import temporary_dir


class AnalysisTools(object):
  """Analysis manipulation methods required by JvmCompile."""
  _PANTS_BUILDROOT_PLACEHOLDER = b'/_PANTS_BUILDROOT_PLACEHOLDER'
  _PANTS_WORKDIR_PLACEHOLDER = b'/_PANTS_WORKDIR_PLACEHOLDER'

  def __init__(self, java_home, parser, analysis_cls, pants_buildroot, pants_workdir):
    self.parser = parser
    self._java_home = java_home
    self._pants_buildroot = pants_buildroot.encode('utf-8')
    self._pants_workdir = pants_workdir.encode('utf-8')
    self._analysis_cls = analysis_cls

  def relativize(self, src_analysis, relativized_analysis):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file1 = os.path.join(tmp_analysis_dir, 'analysis.relativized.1')
      tmp_analysis_file2 = os.path.join(tmp_analysis_dir, 'analysis.relativized.2')

      # NOTE: We can't port references to deps on the Java home. This is because different JVM
      # implementations on different systems have different structures, and there's not
      # necessarily a 1-1 mapping between Java jars on different systems. Instead we simply
      # drop those references from the analysis file.
      #
      # In practice the JVM changes rarely, and it should be fine to require a full rebuild
      # in those rare cases.
      # Work on a tmpfile, for safety.
      # Start with rebasing working directory,
      # because build root cannot be subdirectory of working directory.
      # TODO: Change to one call to zincutils when API will be made: https://github.com/pantsbuild/zincutils/issues/8.
      self.parser.rebase_from_path(src_analysis, tmp_analysis_file1,
                                   self._pants_workdir, self._PANTS_WORKDIR_PLACEHOLDER, self._java_home)
      self.parser.rebase_from_path(tmp_analysis_file1, tmp_analysis_file2,
                                   self._pants_buildroot, self._PANTS_BUILDROOT_PLACEHOLDER, self._java_home)

      shutil.move(tmp_analysis_file2, relativized_analysis)

  def localize(self, src_analysis, localized_analysis):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file1 = os.path.join(tmp_analysis_dir, 'analysis.1')
      tmp_analysis_file2 = os.path.join(tmp_analysis_dir, 'analysys.2')

      # Work on a tmpfile, for safety.
      # TODO: Change to one call to zincutils when API will be made: https://github.com/pantsbuild/zincutils/issues/8.
      self.parser.rebase_from_path(src_analysis, tmp_analysis_file1,
                                   self._PANTS_WORKDIR_PLACEHOLDER, self._pants_workdir)
      self.parser.rebase_from_path(tmp_analysis_file1, tmp_analysis_file2,
                                   self._PANTS_BUILDROOT_PLACEHOLDER, self._pants_buildroot)

      shutil.move(tmp_analysis_file2, localized_analysis)
