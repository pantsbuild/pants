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

  def test_bundle_node_module(self):
    command = ['bundle',
               'contrib/node/examples/src/node/web-component-button']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive('dist/web-component-button.tar.gz') as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json', 'webpack.config.js'])
      )

  def test_bundle_node_preinstalled_module(self):
    command = ['bundle',
               'contrib/node/examples/src/node/preinstalled-project']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive('dist/preinstalled-project.tar.gz') as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json'])
      )

  def test_bundle_node_zip_archive(self):
    command = ['bundle',
               'contrib/node/examples/src/node/preinstalled-project',
               '--bundle-node-archive=zip']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive('dist/preinstalled-project.zip') as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['src', 'test', 'node_modules', 'package.json'])
      )

  def test_bundle_node_with_prefix(self):
    command = ['bundle',
               'contrib/node/examples/src/node/preinstalled-project',
               '--bundle-node-archive-prefix']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

    with self._extract_archive('dist/preinstalled-project.tar.gz') as temp_dir:
      self.assertEquals(
        set(os.listdir(temp_dir)),
        set(['preinstalled-project'])
      )
      self.assertEquals(
        set(os.listdir(os.path.join(temp_dir, 'preinstalled-project'))),
        set(['src', 'test', 'node_modules', 'package.json'])
      )

  @contextmanager
  def _extract_archive(self, archive_path):
    with temporary_dir() as temp_dir:
      archiver_for_path(os.path.basename(archive_path)).extract(archive_path, temp_dir)
      yield temp_dir
