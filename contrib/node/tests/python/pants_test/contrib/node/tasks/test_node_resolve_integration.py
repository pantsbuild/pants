# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeResolveIntegrationTest(PantsRunIntegrationTest):

  def test_resolve_with_prepublish(self):
    command = ['resolve',
               'contrib/node/examples/src/node/server-project']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

  def test_resolve_local_and_3rd_party_dependencies(self):
    command = ['resolve',
               'contrib/node/examples/src/node/web-project']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

  def test_resolve_preinstalled_node_module_project(self):
    command = ['resolve',
               'contrib/node/examples/src/node/preinstalled-project:unit']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

  def test_resolve_source_deps_project(self):
    command = ['resolve',
               'contrib/node/examples/src/node/yarn-workspaces']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

  def test_no_reinstall_with_unchanged_lockfiles(self):
    with self.temporary_workdir() as workdir:
      root = 'contrib/node/examples/src/node/lockfile-invalidation'
      target = root + ':custom-lockfile'
      index_file = os.path.join(root, 'index.js')
      command = ['run', target]
      install_run = self.run_pants_with_workdir(
        command=command,
        workdir=workdir
      )
      self.assert_success(install_run)
      assert "yarn install" in install_run.stdout_data

      with self.with_overwritten_file_content(index_file, temporary_content='console.log("Hello World!!")'):
        fingerprinted_run = self.run_pants_with_workdir(
          command=command,
          workdir=workdir
        )
        self.assert_success(fingerprinted_run)
        assert "yarn install" not in fingerprinted_run.stdout_data

  def test_changing_lockfiles_triggers_reinstall(self):
    with self.temporary_workdir() as workdir:
      root = 'contrib/node/examples/src/node/lockfile-invalidation'
      target = root + ':custom-lockfile'
      package_file = os.path.join(root, 'package.json')
      new_package_contents = dedent("""
      {
        "name": "pantsbuild-hello-node",
        "version": "1.0.1",
        "description": "Pantsbuild hello for Node.js",
        "main": "index.js",
        "repository": "https://github.com/pantsbuild/pants.git",
        "author": "pantsbuild",
        "scripts": {
          "start": "babel-node index.js"
        },
        "devDependencies": {
          "babel-cli": "^6.22.2",
          "babel-preset-latest": "^6.22.0"
        }
      }
      """)

      command = ['run', target]
      install_run = self.run_pants_with_workdir(
        command=command,
        workdir=workdir
      )
      self.assert_success(install_run)
      assert "yarn install" in install_run.stdout_data

      with self.with_overwritten_file_content(package_file, temporary_content=new_package_contents):
        fingerprinted_run = self.run_pants_with_workdir(
          command=command,
          workdir=workdir
        )
        self.assert_success(fingerprinted_run)
        assert "yarn install" in fingerprinted_run.stdout_data

  def test_specify_custom_monitored_lockfiles(self):
    with self.temporary_workdir() as workdir:
      root = 'contrib/node/examples/src/node/lockfile-invalidation'
      target = root + ':custom-lockfile'
      custom_lockfile_basename = 'custom_lockfile'
      custom_lockfile_path = os.path.join(root, custom_lockfile_basename)
      command = [
        'run',
        '--resolve-node-install-invalidating-files=+["{}"]'.format(custom_lockfile_basename),
        target
      ]
      install_run = self.run_pants_with_workdir(
        command=command,
        workdir=workdir
      )
      self.assert_success(install_run)
      assert "yarn install" in install_run.stdout_data

      with self.with_overwritten_file_content(custom_lockfile_path, temporary_content="Roland"):
        fingerprinted_run = self.run_pants_with_workdir(
          command=command,
          workdir=workdir
        )
        self.assert_success(fingerprinted_run)
        assert "yarn install" in fingerprinted_run.stdout_data

  def test_monitoring_lockfile_outside_of_sources_throws(self):
    with self.temporary_workdir() as workdir:
      root = 'contrib/node/examples/src/node/lockfile-invalidation'
      target = root + ':custom-lockfile'
      custom_lockfile_basename = 'custom_lockfile_not_in_sources'
      command = [
        'run',
        '--resolve-node-install-invalidating-files=+["{}"]'.format(custom_lockfile_basename),
        target
      ]
      install_run = self.run_pants_with_workdir(
        command=command,
        workdir=workdir
      )
      self.assert_failure(install_run)
