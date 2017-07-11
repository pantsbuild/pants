# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeTestIntegrationTest(PantsRunIntegrationTest):

  def test_test_simple(self):
    command = ['test',
               'contrib/node/examples/src/node/server-project:unit']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

  def test_test_target_with_non_default_script_name(self):
    command = ['test',
               'contrib/node/examples/src/node/web-component-button:unit']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

  def test_test_multiple_targets(self):
    command = ['test',
               'contrib/node/examples/src/node/web-component-button:unit',
               'contrib/node/examples/src/node/web-component-button:integration']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

  def test_test_preinstalled_node_module_project(self):
    # Run pants twice to make sure `NodePaths` product is set correctly for valid vts
    # as well on the second run.
    with self.temporary_workdir() as workdir:
      for _ in range(2):
        command = ['test',
                   'contrib/node/examples/src/node/preinstalled-project:unit']
        pants_run = self.run_pants_with_workdir(command=command, workdir=workdir)
        self.assert_success(pants_run)

  def test_test_passthru_args(self):
    command = ['-q',
               'test',
               'contrib/node/examples/src/node/server-project:checkarg',
               '--']

    pants_run = self.run_pants(command=command + ['incorrect'])
    self.assert_failure(pants_run)

    pants_run = self.run_pants(command=command + ['correct'])
    self.assert_success(pants_run)
