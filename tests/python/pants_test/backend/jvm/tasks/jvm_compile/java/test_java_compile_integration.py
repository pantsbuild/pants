# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.fs.archive import TarArchiver
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


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
      bad_artifact_dir = os.path.join(cache_dir,
          ZincCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.nocache.nocache')
      good_artifact_dir = os.path.join(cache_dir,
          ZincCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.nocache.cache_me')
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(['compile',
                                  'testprojects/src/java/org/pantsbuild/testproject/nocache::'],
                                 config)
      self.assert_success(pants_run)

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
      artifact_dir = os.path.join(cache_dir, ZincCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main')
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(self.create_platform_args(6) +
                                 ['compile',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 6
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for java 7
      pants_run = self.run_pants(self.create_platform_args(7) +
                                 ['compile',
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main'],
                                 config)
      self.assert_success(pants_run)

      # One artifact for java 6 and one for 7
      self.assertEqual(len(os.listdir(artifact_dir)), 2)

  def test_java_compile_reads_resource_mapping(self):
    # Ensure that if an annotation processor produces a resource-mapping,
    # the artifact contains that resource mapping.

    with temporary_dir() as cache_dir:
      artifact_dir = os.path.join(cache_dir, ZincCompile.stable_name(),
          'testprojects.src.java.org.pantsbuild.testproject.annotation.main.main')
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}

      pants_run = self.run_pants(['compile',
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
      artifact_dir = os.path.join(cache_dir, ZincCompile.stable_name(),
                                  '{}.jarversionincompatibility'.format(dotted_path))
      config = {
          'cache.compile.zinc': {
            'write_to': [cache_dir],
            'read_from': [cache_dir],
          },
          'compile.zinc': {
            'incremental_caching': True,
          },
      }

      pants_run = self.run_pants_with_workdir(['compile',
                                               ('{}:only-15-directly'.format(path_prefix))],
                                              workdir,
                                              config)
      self.assert_success(pants_run)

      # One artifact for guava 15
      self.assertEqual(len(os.listdir(artifact_dir)), 1)

      # Rerun for guava 16
      pants_run = self.run_pants_with_workdir(['compile',
                                               (u'{}:alongside-16'.format(path_prefix))],
                                              workdir,
                                              config)
      self.assert_success(pants_run)

      # One artifact for guava 15 and one for guava 16
      self.assertEqual(len(os.listdir(artifact_dir)), 2)


class JavaCompileIntegrationTestWithZjar(JavaCompileIntegrationTest):
  _EXTRA_TASK_ARGS = ['--compile-zinc-use-classpath-jars']
