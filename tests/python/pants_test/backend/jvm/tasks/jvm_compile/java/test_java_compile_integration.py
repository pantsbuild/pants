# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.java.java_compile import JmakeCompile
from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis_parser import JMakeAnalysisParser
from pants.fs.archive import TarArchiver
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.testutils.compile_strategy_utils import provide_compile_strategies


class JavaCompileIntegrationTest(BaseCompileIT):

  def _java_compile_produces_valid_analysis_file(self, workdir):
    # A bug was introduced where if a java compile was run twice, the second
    # time the global_analysis.valid file would incorrectly be empty.

    pants_run = self.run_pants_with_workdir([
        'compile',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main'],
        workdir)
    self.assert_success(pants_run)

    # Parse the analysis file from the compilation.
    analysis_file = os.path.join(workdir, 'compile', 'jvm', 'java', 'analysis',
                                 'global_analysis.valid')
    parser = JMakeAnalysisParser()
    analysis = parser.parse_from_path(analysis_file)

    # Ensure we have entries in the analysis file.
    self.assertEquals(len(analysis.pcd_entries), 2)

  def test_java_compile_produces_valid_analysis_file_second_time(self):
    # Run the test above twice to ensure it works both times.
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      self._java_compile_produces_valid_analysis_file(workdir)
      self._java_compile_produces_valid_analysis_file(workdir)

  @provide_compile_strategies
  def test_resources_by_target_and_partitions(self, strategy):
    """
    This tests that resources_by_target interacts correctly with
    partitions; we want to make sure that even targets that are outside
    the current partition don't cause crashes when they are looked up in
    resources_by_targets (see jvm_compile.py).
    """
    with temporary_dir() as cache_dir:
      config = {'cache.compile.java': {'write_to': [cache_dir]}}

      with temporary_dir(root_dir=self.workdir_root()) as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile', 'compile.java', '--strategy={}'.format(strategy), '--partition-size-hint=1',
           'testprojects/src/java/org/pantsbuild/testproject/publish/hello/main:',
         ],
          workdir, config)
        self.assert_success(pants_run)

  @provide_compile_strategies
  def test_nocache(self, strategy):
    with temporary_dir() as cache_dir:
      bad_artifact_dir = os.path.join(cache_dir,
          JmakeCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.nocache.nocache')
      good_artifact_dir = os.path.join(cache_dir,
          JmakeCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.nocache.cache_me')
      config = {'cache.compile.java': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(['compile.java',
                                  '--strategy={}'.format(strategy),
                                  'testprojects/src/java/org/pantsbuild/testproject/nocache::'],
                                 config)
      self.assert_success(pants_run)

      # The nocache target is labeled with no_cache so it should not be written to the
      # artifact cache.
      self.assertFalse(os.path.exists(bad_artifact_dir))
      # But cache_me should be written.
      self.assertEqual(len(os.listdir(good_artifact_dir)), 1)

  # TODO(John Sirois): Factor up a shared utility for reuse by
  # tests/python/pants_test/backend/core/tasks/test_cache_cleanup.py
  def create_platform_args(self, version):
    return [("""--jvm-platform-platforms={{'default': {{'target': '{version}'}}}}"""
             .format(version=version)),
            '--jvm-platform-default-platform=default']

  @provide_compile_strategies
  def test_java_compile_produces_different_artifact_depending_on_java_version(self, strategy):
    # Ensure that running java compile with java 6 and then java 7
    # produces two different artifacts.

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, JmakeCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main')
      config = {'cache.compile.java': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(self.create_platform_args(6) +
                                 ['compile.java',
                                  '--strategy={}'.format(strategy),
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 6
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for java 7
      pants_run = self.run_pants(self.create_platform_args(7) +
                                 ['compile.java',
                                  '--strategy={}'.format(strategy),
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 6 and one for 7
      self.assertEqual(len(os.listdir(artifact_dir)), 2)

  @provide_compile_strategies
  def test_java_compile_reads_resource_mapping(self, strategy):
    # Ensure that if an annotation processor produces a resource-mapping,
    # the artifact contains that resource mapping.

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir,
          JmakeCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.annotation.main.main')
      config = {'cache.compile.java': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(['compile.java',
                                  '--strategy={}'.format(strategy),
                                  'compile.apt',
                                  '--strategy={}'.format(strategy),
                                  'testprojects/src/java/org/pantsbuild/testproject/annotation/main'],
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

        # Locate the report file on the classpath.
        report_file_name = 'deprecation_report.txt'
        reports = [f for f in all_files if f.endswith(report_file_name)]
        self.assertEquals(1, len(reports),
                          'Expected exactly one {} file; got: {}'.format(report_file_name,
                                                                         all_files))

        with open(reports[0]) as fp:
          annotated_classes = [line.rstrip() for line in fp.read().splitlines()]
          self.assertEquals(
            {'org.pantsbuild.testproject.annotation.main.Main',
             'org.pantsbuild.testproject.annotation.main.Main$TestInnerClass'},
            set(annotated_classes))

  def _whitelist_test(self, target, whitelist_target, strategy, fatal_flag, args=None):
    """Ensure that a project missing dependencies fails if it is not whitelisted."""

    # First check that without the whitelist we do break the build.
    extra_args = (args if args else []) + [fatal_flag]
    with self.do_test_compile(target, strategy, extra_args=extra_args, expect_failure=True):
      # run failed as expected
      pass

    # Now let's use the target whitelist, this should succeed.
    extra_args = (args if args else []) + [
        fatal_flag,
        '--compile-jvm-dep-check-missing-deps-whitelist=["{}"]'.format(whitelist_target)
      ]
    with self.do_test_compile(target, strategy, extra_args=extra_args):
      # run succeeded as expected
      pass

  def test_java_compile_missing_dep_analysis_whitelist(self):
    self._whitelist_test(
      'testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist',
      'testprojects/src/java/org/pantsbuild/testproject/missingdepswhitelist2',
      # NB: missing transitive deps are only possible with the global strategy
      'global',
      '--compile-jvm-dep-check-missing-deps=fatal'
    )

  @provide_compile_strategies
  def test_java_compile_missing_direct_dep_analysis_whitelist_jmake(self, strategy):
    self._whitelist_test(
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist',
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist',
      strategy,
      '--compile-jvm-dep-check-missing-direct-deps=fatal'
    )

  @provide_compile_strategies
  def test_java_compile_missing_direct_dep_analysis_whitelist_zinc(self, strategy):
    self._whitelist_test(
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist',
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist',
      strategy,
      '--compile-jvm-dep-check-missing-direct-deps=fatal',
      # Use zinc.
      args=['--no-compile-java-use-jmake']
    )

  @provide_compile_strategies
  def test_java_compile_missing_jar_dep_analysis_whitelist_zinc(self, strategy):
    self._whitelist_test(
      'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist',
      'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist',
      strategy,
      '--compile-jvm-dep-check-missing-direct-deps=fatal',
      # Use zinc.
      args=['--no-compile-java-use-jmake']
    )
