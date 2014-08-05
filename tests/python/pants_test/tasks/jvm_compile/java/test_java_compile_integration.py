# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
import os

from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis_parser import JMakeAnalysisParser

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JavaCompileIntegrationTest(PantsRunIntegrationTest):

  def _java_compile_produces_valid_analysis_file(self, workdir):
    # A bug was introduced where if a java compile was run twice, the second
    # time the global_analysis.valid file would incorrectly be empty.

    pants_run = self.run_pants_with_workdir(
      ['goal', 'compile', 'src/java/com/pants/testproject/unicode/main'],
      workdir)
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal compile expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

    # Parse the analysis file from the compilation.
    analysis_file = os.path.join(workdir, 'compile', 'jvm', 'java', 'analysis', 'global_analysis.valid')
    parser = JMakeAnalysisParser('not_used')
    analysis = parser.parse_from_path(analysis_file)

    # Ensure we have entries in the analysis file.
    self.assertEquals(len(analysis.pcd_entries), 2)


  def test_java_compile_produces_valid_analysis_file_second_time(self):
    # Run the test above twice to ensure it works both times.
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      self._java_compile_produces_valid_analysis_file(workdir)
      self._java_compile_produces_valid_analysis_file(workdir)


