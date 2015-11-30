# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

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
    command = ['test',
               'contrib/node/examples/src/node/preinstalled-project:unit']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)
