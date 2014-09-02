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

  def _assert_run_success(self, pants_run):
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal compile expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

  def _java_compile_produces_valid_analysis_file(self, workdir):
    # A bug was introduced where if a java compile was run twice, the second
    # time the global_analysis.valid file would incorrectly be empty.

    pants_run = self.run_pants_with_workdir(
      ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/unicode/main'],
      workdir)
    self._assert_run_success(pants_run)

    # Parse the analysis file from the compilation.
    analysis_file = os.path.join(workdir, 'compile', 'jvm', 'java', 'analysis',
                                 'global_analysis.valid')
    parser = JMakeAnalysisParser('not_used')
    analysis = parser.parse_from_path(analysis_file)

    # Ensure we have entries in the analysis file.
    self.assertEquals(len(analysis.pcd_entries), 2)

  def test_java_compile_produces_valid_analysis_file_second_time(self):
    # Run the test above twice to ensure it works both times.
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      self._java_compile_produces_valid_analysis_file(workdir)
      self._java_compile_produces_valid_analysis_file(workdir)

  def test_java_compile_produces_different_artifact_depending_on_java_version(self):
    # Ensure that running java compile with java 6 and then java 7
    # produces two different artifacts.

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, 'JavaCompile',
                                  'testprojects.src.java.com.pants.testproject.unicode.main.main')
      config = {'java-compile': {'write_artifact_caches': [cache_dir]}}

      pants_run = self.run_pants(
        ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/unicode/main'],
        config)
      self._assert_run_success(pants_run)

      # One artifact for java 6
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for java 7
      pants_run = self.run_pants(
        ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/unicode/main',
         '--compile-java-args=\'-target 1.7\''],
        config)
      self._assert_run_success(pants_run)

      # One artifact for java 6 and one for 7
      self.assertEqual(len(os.listdir(artifact_dir)), 2)
