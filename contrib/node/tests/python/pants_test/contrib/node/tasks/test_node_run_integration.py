# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeRunIntegrationTest(PantsRunIntegrationTest):

  def test_run_simple(self):
    command = ['run',
               'contrib/node/examples/src/node/web-component-button',
               '--run-node-script-name=build']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

  def test_run_passthru_args(self):
    command = ['-q',
               'run',
               'contrib/node/examples/src/node/server-project',
               '--run-node-script-name=checkarg',
               '--']

    pants_run = self.run_pants(command=command + ['incorrect'])
    self.assert_failure(pants_run)

    pants_run = self.run_pants(command=command + ['correct'])
    self.assert_success(pants_run)

  def test_run_yarnpkg(self):
    command = ['run',
               'contrib/node/examples/src/node/hello:pantsbuild-hello-node',
               '--run-node-script-name=start']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

  def test_run_yarnpkg_source_deps_with_workspaces(self):
    command = ['run',
               'contrib/node/examples/src/node/yarn-workspaces',
               '--run-node-script-name=test-adder']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
