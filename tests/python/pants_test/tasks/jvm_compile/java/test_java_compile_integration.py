# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis_parser import JMakeAnalysisParser
from pants.fs.archive import TarArchiver
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JavaCompileIntegrationTest(PantsRunIntegrationTest):

  def _java_compile_produces_valid_analysis_file(self, workdir):
    # A bug was introduced where if a java compile was run twice, the second
    # time the global_analysis.valid file would incorrectly be empty.

    pants_run = self.run_pants_with_workdir(
      ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/unicode/main'],
      workdir)
    self.assert_success(pants_run)

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

  def test_nocache(self):
    with temporary_dir() as cache_dir:
      bad_artifact_dir = os.path.join(cache_dir, 'JavaCompile',
                                  'testprojects.src.java.com.pants.testproject.nocache.nocache')
      good_artifact_dir = os.path.join(cache_dir, 'JavaCompile',
                                  'testprojects.src.java.com.pants.testproject.nocache.cache_me')
      config = {'java-compile': {'write_artifact_caches': [cache_dir]}}

      pants_run = self.run_pants(
        ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/nocache::'],
        config)
      self.assert_success(pants_run)

      # The nocache target is labeled with no_cache so it should not be written to the
      # artifact cache.
      self.assertFalse(os.path.exists(bad_artifact_dir))
      # But cache_me should be written.
      self.assertEqual(len(os.listdir(good_artifact_dir)), 1)

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
      self.assert_success(pants_run)

      # One artifact for java 6
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for java 7
      pants_run = self.run_pants(
        ['goal', 'compile.java', '--target=1.7',
         'testprojects/src/java/com/pants/testproject/unicode/main'],
        config)
      self.assert_success(pants_run)

      # One artifact for java 6 and one for 7
      self.assertEqual(len(os.listdir(artifact_dir)), 2)


  def test_java_compile_reads_resource_mapping(self):
    # Ensure that if an annotation processor produces a resource-mapping,
    # the artifact contains that resource mapping.

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, 'JavaCompile',
                                  'testprojects.src.java.com.pants.testproject.annotation.main.main')
      config = {'java-compile': {'write_artifact_caches': [cache_dir]}}

      pants_run = self.run_pants(
        ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/annotation/main'],
        config)
      self.assert_success(pants_run)

      self.assertTrue(os.path.exists(artifact_dir))
      artifacts = os.listdir(artifact_dir)
      self.assertEqual(len(artifacts), 1)

      with temporary_dir() as extract_dir:
        TarArchiver.extract(os.path.join(artifact_dir, artifacts[0]), extract_dir)
        all_files = set()
        for dirpath, dirs, files in safe_walk(extract_dir):
          for name in files:
            path = os.path.join(dirpath, name)
            all_files.add(path)

        report_file_name = os.path.join(extract_dir, 'compile/jvm/java/classes/deprecation_report.txt')
        self.assertIn(report_file_name, all_files)

        annotated_classes = [line.rstrip() for line in file(report_file_name).read().splitlines()]
        self.assertEquals(
          {'com.pants.testproject.annotation.main.Main', 'com.pants.testproject.annotation.main.Main$TestInnerClass'},
          set(annotated_classes))

  def _whitelist_test(self, target, fatal_flag, whitelist):
    # We want to ensure that a project missing dependencies can be
    # whitelisted so that the missing deps do not break the build.

    args = [
      'goal',
      'compile',
      target,
      fatal_flag
    ]

    # First check that without the whitelist we do break the build.
    pants_run = self.run_pants(args, {})
    self.assertNotEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE)

    # Now let's use the target whitelist, this should succeed.
    config = {
      'jvm': {'missing_deps_target_whitelist': [whitelist]}
    }

    pants_run = self.run_pants(args, config)

    self.assert_success(pants_run)


  def test_java_compile_missing_dep_analysis_whitelist(self):
    self._whitelist_test(
      'testprojects/src/java/com/pants/testproject/missingdepswhitelist',
      '--compile-java-missing-deps=fatal',
      'testprojects/src/java/com/pants/testproject/missingdepswhitelist2'
    )


  def test_java_compile_missing_direct_dep_analysis_whitelist(self):
    self._whitelist_test(
      'testprojects/src/java/com/pants/testproject/missingdirectdepswhitelist',
      '--compile-java-missing-direct-deps=fatal',
      'testprojects/src/java/com/pants/testproject/missingdirectdepswhitelist'
    )
