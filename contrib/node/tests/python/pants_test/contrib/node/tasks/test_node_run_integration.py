# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeRunIntegrationTest(PantsRunIntegrationTest):

  def test_run_simple(self):
    command = ['run',
               'contrib/node/examples/src/node/web-component-button',
               '--run-node-script-name=build']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)
