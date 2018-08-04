# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open

from pants.fs.archive import archiver_for_path
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.cache.cache_server import cache_server


class JavaCompileIntegrationTest(BaseCompileIT):

  def test_basic_binary(self):
    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile',
           'testprojects/src/java/org/pantsbuild/testproject/publish/hello/main:',
         ],
          workdir, config)
        self.assert_success(pants_run)

  def test_nocache(self):
    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      self.assert_success(self.run_pants([
        'compile',
        'testprojects/src/java/org/pantsbuild/testproject/nocache::',
      ], config=config))

      zinc_task_dir = self.get_cache_subdir(cache_dir)

      bad_artifact_dir = os.path.join(zinc_task_dir, 'testprojects.src.java.org.pantsbuild.testproject.nocache.nocache')
      good_artifact_dir = os.path.join(zinc_task_dir, 'testprojects.src.java.org.pantsbuild.testproject.nocache.cache_me')
      # The nocache target is labeled with no_cache so it should not be written to the
      # artifact cache.
      self.assertFalse(os.path.exists(bad_artifact_dir))
      # But cache_me should be written.
      self.assertEqual(len(os.listdir(good_artifact_dir)), 1)

  # TODO(John Sirois): Factor up a shared utility for reuse by
  # tests/python/pants_test/backend/core/tasks/test_cache_cleanup_integration.py
  def create_platform_args(self, version):
    return [("""--jvm-platform-platforms={{'default': {{'target': '{version}'}}}}"""
             .format(version=version)),
            '--jvm-platform-default-platform=default']

  def test_java_compile_produces_different_artifact_depending_on_java_version(self):
    # Ensure that running java compile with java 6 and then java 7
    # produces two different artifacts.

    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      java_6_args = self.create_platform_args(6) + [
        'compile',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
      ]
      self.assert_success(self.run_pants(java_6_args, config))

      java_6_artifact_dir = self.get_cache_subdir(cache_dir)
      main_java_6_dir = os.path.join(
        java_6_artifact_dir,
        'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
      )
      # One artifact for java 6
      self.assertEqual(len(os.listdir(main_java_6_dir)), 1)

      # Rerun for java 7
      java_7_args = self.create_platform_args(7) + [
        'compile',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
      ]
      self.assert_success(self.run_pants(java_7_args, config))

      java_7_artifact_dir = self.get_cache_subdir(
        cache_dir,
        other_dirs=[java_6_artifact_dir],
      )
      main_java_7_dir = os.path.join(
        java_7_artifact_dir,
        'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
      )
      # java 7 platform args should change the result dir name
      self.assertEqual(len(os.listdir(main_java_7_dir)), 1)

  def test_java_compile_reads_resource_mapping(self):
    # Ensure that if an annotation processor produces a resource-mapping,
    # the artifact contains that resource mapping.

    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      self.assert_success(self.run_pants([
        'compile',
        'testprojects/src/java/org/pantsbuild/testproject/annotation/main',
      ], config=config))

      base_artifact_dir = self.get_cache_subdir(cache_dir)
      artifact_dir = os.path.join(
        base_artifact_dir,
        'testprojects.src.java.org.pantsbuild.testproject.annotation.main.main',
      )

      self.assertTrue(os.path.exists(artifact_dir))
      artifacts = os.listdir(artifact_dir)
      self.assertEqual(len(artifacts), 1)
      single_artifact = artifacts[0]

      with temporary_dir() as extract_dir:
        artifact_path = os.path.join(artifact_dir, single_artifact)
        archiver_for_path(artifact_path).extract(artifact_path, extract_dir)
        all_files = set()
        for dirpath, dirs, files in safe_walk(extract_dir):
          for name in files:
            path = os.path.join(dirpath, name)
            all_files.add(path)

        # Locate the report file on the classpath.
        report_file_name = 'deprecation_report.txt'
        reports = [f for f in all_files if f.endswith(report_file_name)]
        self.assertEqual(1, len(reports),
                          'Expected exactly one {} file; got: {}'.format(report_file_name,
                                                                         all_files))

        with open(reports[0], 'r') as fp:
          annotated_classes = [line.rstrip() for line in fp.read().splitlines()]
          self.assertEqual(
            {'org.pantsbuild.testproject.annotation.main.Main',
             'org.pantsbuild.testproject.annotation.main.Main$TestInnerClass'},
            set(annotated_classes))

  def test_java_compile_with_changes_in_resources_dependencies(self):
    with self.source_clone('testprojects/src/java/org/pantsbuild/testproject/resdependency') as resdependency:
      with self.temporary_workdir() as workdir:
        with self.temporary_cachedir() as cachedir:
          target = os.path.join(resdependency, 'java:testsources')

          first_run = self.run_test_compile(workdir, cachedir, target, clean_all=True)
          self.assert_success(first_run)
          self.assertTrue("Compiling" in first_run.stdout_data)

          with open(os.path.join(resdependency, 'resources/resource.xml'), 'w') as xml_resource:
            xml_resource.write('<xml>Changed Hello World</xml>\n')

          second_run = self.run_test_compile(workdir, cachedir, target, clean_all=False)
          self.assert_success(second_run)
          self.assertTrue("Compiling" not in second_run.stdout_data,
                          "In case of resources change nothing should be recompiled")

  def test_java_compile_with_different_resolved_jars_produce_different_artifacts(self):
    # Since unforced dependencies resolve to the highest version including transitive jars,
    # We want to ensure that running java compile with binary incompatible libraries will
    # produces two different artifacts.

    with self.temporary_workdir() as workdir, temporary_dir() as cache_dir:
      path_prefix = 'testprojects/src/java/org/pantsbuild/testproject/jarversionincompatibility'
      dotted_path = path_prefix.replace(os.path.sep, '.')

      config = {
          'cache.compile.zinc': {
            'write_to': [cache_dir],
            'read_from': [cache_dir],
          },
          'compile.zinc': {
            'incremental_caching': True,
          },
      }

      self.assert_success(self.run_pants_with_workdir([
        'compile',
        '{}:only-15-directly'.format(path_prefix),
      ], workdir, config))
      guava_15_base_dir = self.get_cache_subdir(cache_dir)
      guava_15_artifact_dir = os.path.join(
        guava_15_base_dir,
        '{}.jarversionincompatibility'.format(dotted_path),
      )

      # One artifact for guava 15
      self.assertEqual(len(os.listdir(guava_15_artifact_dir)), 1)

      # Rerun for guava 16
      self.assert_success(self.run_pants_with_workdir([
        'compile',
        (u'{}:alongside-16'.format(path_prefix)),
      ], workdir, config))

      guava_16_base_dir = self.get_cache_subdir(cache_dir)
      # the zinc compile task has the same option values in both runs, so the
      # results directory should be the same
      guava_16_artifact_dir = os.path.join(
        guava_16_base_dir,
        '{}.jarversionincompatibility'.format(dotted_path),
      )

      # One artifact for guava 15 and one for guava 16
      self.assertEqual(guava_16_artifact_dir, guava_15_artifact_dir)
      self.assertEqual(len(os.listdir(guava_16_artifact_dir)), 2)

  def test_java_compile_with_corrupt_remote(self):
    """Tests that a corrupt artifact in the remote cache still results in a successful compile."""
    with self.temporary_workdir() as workdir, temporary_dir() as cachedir:
      with cache_server(cache_root=cachedir) as server:
        target = 'testprojects/tests/java/org/pantsbuild/testproject/matcher'
        config = {
            'cache.compile.zinc': {
              'write_to': [server.url],
              'read_from': [server.url],
            },
        }

        # Compile to populate the cache, and actually run the tests to help verify runtime.
        first_run = self.run_pants_with_workdir(['test', target], workdir, config)
        self.assert_success(first_run)
        self.assertTrue("Compiling" in first_run.stdout_data)

        # Build again to hit the cache.
        second_run = self.run_pants_with_workdir(['clean-all', 'test', target], workdir, config)
        self.assert_success(second_run)
        self.assertFalse("Compiling" in second_run.stdout_data)

        # Corrupt the remote artifact.
        self.assertEqual(server.corrupt_artifacts(r'.*'), 1)

        # Ensure that the third run succeeds, despite a failed attempt to fetch.
        third_run = self.run_pants_with_workdir(['clean-all', 'test', target], workdir, config)
        self.assert_success(third_run)
        self.assertTrue("Compiling" in third_run.stdout_data)


class JavaCompileIntegrationTestWithZjar(JavaCompileIntegrationTest):
  _EXTRA_TASK_ARGS = ['--compile-zinc-use-classpath-jars']
