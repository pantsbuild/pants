# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.fs.archive import archiver, archiver_for_path
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeBundleIntegrationTest(PantsRunIntegrationTest):

  DIST_DIR = 'dist'
  TGZ_SUFFIX = '.tar.gz'
  JAR_SUFFIX = '.jar'

  PROJECT_DIR = 'contrib/node/examples/src/node/web-component-button'
  WEB_COMPONENT_BUTTON_PROJECT = 'web-component-button'
  WEB_COMPONENT_BUTTON_PROCESSED_PROJECT = 'web-component-button-processed'
  WITH_DEPENDENCY_ARTIFACTS_PROJECT = 'web-component-button-processed-with-dependency-artifacts'

  WEB_COMPONENT_BUTTON_BUNDLE = 'web-component-button-bundle'
  WEB_COMPONENT_BUTTON_PROCESSED_BUNDLE = 'web-component-button-processed-bundle'

  PREINSTALLED_PROJECT_DIR = 'contrib/node/examples/src/node/preinstalled-project'
  PREINSTALLED_PROJECT = 'preinstalled-project'
  PREINSTALLED_BUNDLE = 'preinstalled-project-bundle'

  JVM_PROJECT = 'jsresources'
  JVM_WITH_ARTIFACTS_PROJECT = 'jsresources-with-dependency-artifacts'
  JVM_PROJECT_DIR = 'contrib/node/examples/src/java/org/pantsbuild/testproject/jsresources'

  WEB_COMPONENT_BUTTON_ARTIFACT = os.path.join(
    DIST_DIR, WEB_COMPONENT_BUTTON_BUNDLE + TGZ_SUFFIX)
  WEB_COMPONENT_BUTTON_PROCESSED_ARTIFACT = os.path.join(
    DIST_DIR, WEB_COMPONENT_BUTTON_PROCESSED_BUNDLE + TGZ_SUFFIX)
  PREINSTALLED_ARTIFACT = os.path.join(
    DIST_DIR, PREINSTALLED_BUNDLE + TGZ_SUFFIX)

  JVM_PROJECT_ARTIFACT = os.path.join(DIST_DIR, JVM_PROJECT + JAR_SUFFIX)
  JVM_WITH_ARTIFACTS_ARTIFACT = os.path.join(DIST_DIR, JVM_WITH_ARTIFACTS_PROJECT + JAR_SUFFIX)

  def test_bundle_node_module(self):
    command = [
      'bundle',
      ':'.join([self.PROJECT_DIR, self.WEB_COMPONENT_BUTTON_BUNDLE])]
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive(self.WEB_COMPONENT_BUTTON_ARTIFACT) as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json', 'webpack.config.js'])
      )
      # Make sure .bin symlinks remains as symlinks.
      self.assertTrue(os.path.islink(os.path.join(temp_dir, 'node_modules', '.bin', 'mocha')))

  def test_bundle_node_module_processed(self):
    command = [
      'bundle',
      ':'.join([self.PROJECT_DIR, self.WEB_COMPONENT_BUTTON_PROCESSED_BUNDLE])]
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive(self.WEB_COMPONENT_BUTTON_PROCESSED_ARTIFACT) as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['Button.js'])
      )

  def test_bundle_jvm_binary_with_node_module(self):
    command = [
      'binary',
      ':'.join([self.JVM_PROJECT_DIR, self.JVM_PROJECT])
      ]
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive(self.JVM_PROJECT_ARTIFACT) as temp_dir:
      self.assertEquals(
        set(os.listdir(os.path.join(temp_dir, self.WEB_COMPONENT_BUTTON_PROCESSED_PROJECT))),
        set(['Button.js'])
      )
      # Only include node build results, not original node_modules directory
      self.assertTrue('node_modules' not in os.listdir(temp_dir))
      # Transitive dependency that marked as not generating artifacts should not be included.
      self.assertTrue('web-build-tool' not in os.listdir(temp_dir))

  def test_bundle_jvm_binary_with_node_module_and_dependencies(self):
    command = [
      'binary',
      ':'.join([self.JVM_PROJECT_DIR, self.JVM_WITH_ARTIFACTS_PROJECT])
      ]
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive(self.JVM_WITH_ARTIFACTS_ARTIFACT) as temp_dir:
      print (os.listdir(temp_dir))
      self.assertEquals(
        set(os.listdir(os.path.join(temp_dir, self.WITH_DEPENDENCY_ARTIFACTS_PROJECT))),
        set(['Button.js'])
      )
      # Only include node build results, not original node_modules directory
      self.assertTrue('node_modules' not in os.listdir(temp_dir))
      # Transitive dependency should not be included.
      self.assertTrue('web-dependency-test' in os.listdir(temp_dir))

  def test_bundle_node_preinstalled_module(self):
    command = [
      'bundle',
      ':'.join([self.PREINSTALLED_PROJECT_DIR, self.PREINSTALLED_BUNDLE])]
    self.assert_success(self.run_pants(command=command))

    with self._extract_archive(self.PREINSTALLED_ARTIFACT) as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json'])
      )

  def test_no_bundle_for_node_module(self):
    command = ['bundle', ':'.join([self.PREINSTALLED_PROJECT_DIR, self.PREINSTALLED_PROJECT])]
    self.assert_success(self.run_pants(command=command))
    self.assertFalse(os.path.exists(self.PREINSTALLED_BUNDLE))

  @contextmanager
  def _extract_archive(self, archive_path):
    with temporary_dir() as temp_dir:
      _, extension = os.path.splitext(archive_path)
      print (extension)
      if extension == '.jar':
        extraction_archiver = archiver('zip')
      else:
        extraction_archiver = archiver_for_path(os.path.basename(archive_path))
      extraction_archiver.extract(archive_path, temp_dir)
      yield temp_dir
