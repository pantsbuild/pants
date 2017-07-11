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
    self.rebase_mappings = {self._pants_workdir: self._PANTS_WORKDIR_PLACEHOLDER,
                            self._pants_buildroot: self._PANTS_BUILDROOT_PLACEHOLDER}
    self.localize_mappings = {v:k for k, v in self.rebase_mappings.items()}

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
      self.parser.rebase_from_path(src_analysis, tmp_analysis_file, self.rebase_mappings, self._java_home)

      shutil.move(tmp_analysis_file, relativized_analysis)

  def localize(self, src_analysis, localized_analysis):
    with temporary_dir() as tmp_analysis_dir:
      tmp_analysis_file = os.path.join(tmp_analysis_dir, 'analysis')

      # Work on a tmpfile, for safety.
      self.parser.rebase_from_path(src_analysis, tmp_analysis_file, self.localize_mappings)

      shutil.move(tmp_analysis_file, localized_analysis)
