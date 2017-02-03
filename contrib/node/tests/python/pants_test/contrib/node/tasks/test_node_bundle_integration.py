# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.fs.archive import archiver_for_path
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeBundleIntegrationTest(PantsRunIntegrationTest):

  PROJECT_DIR = 'contrib/node/examples/src/node'
  DIST_DIR = 'dist'
  WEB_COMPONENT_BUTTON_PROJECT = 'web-component-button'
  WEB_COMPONENT_BUTTON_PROJECT_BUNDLE = WEB_COMPONENT_BUTTON_PROJECT + '-bundle'
  PREINSTALLED_PROJECT = 'preinstalled-project'
  PREINSTALLED_PROJECT_BUNDLE = PREINSTALLED_PROJECT + '-bundle'
  TGZ_SUFFIX = 'tar.gz'

  WEB_COMPONENT_BUTTON_ARTIFACT = os.path.join(
    DIST_DIR, WEB_COMPONENT_BUTTON_PROJECT_BUNDLE + '.' + TGZ_SUFFIX)
  PREINSTALLED_ARTIFACT = os.path.join(
    DIST_DIR, PREINSTALLED_PROJECT_BUNDLE + '.' + TGZ_SUFFIX)

  def test_bundle_node_module(self):
    command = [
      'bundle',
      ':'.join([
        os.path.join(self.PROJECT_DIR, self.WEB_COMPONENT_BUTTON_PROJECT),
        self.WEB_COMPONENT_BUTTON_PROJECT_BUNDLE])]
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive(self.WEB_COMPONENT_BUTTON_ARTIFACT) as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json', 'webpack.config.js'])
      )
      # Make sure .bin symlinks remains as symlinks.
      self.assertTrue(os.path.islink(os.path.join(temp_dir, 'node_modules', '.bin', 'mocha')))

  def test_bundle_node_preinstalled_module(self):
    command = [
      'bundle',
      ':'.join([
        os.path.join(self.PROJECT_DIR, self.PREINSTALLED_PROJECT),
        self.PREINSTALLED_PROJECT_BUNDLE])]
    self.assert_success(self.run_pants(command=command))

    with self._extract_archive(self.PREINSTALLED_ARTIFACT) as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json'])
      )

  def test_no_bundle_for_node_module(self):
    command = ['bundle', os.path.join(self.PROJECT_DIR, self.PREINSTALLED_PROJECT)]
    self.assert_success(self.run_pants(command=command))
    self.assertFalse(os.path.exists(self.PREINSTALLED_PROJECT_BUNDLE))

  @contextmanager
  def _extract_archive(self, archive_path):
    with temporary_dir() as temp_dir:
      archiver_for_path(os.path.basename(archive_path)).extract(archive_path, temp_dir)
      yield temp_dir
