# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeRunIntegrationTest(PantsRunIntegrationTest):

  def test_lint_success(self):
    command = ['lint',
               'contrib/node/examples/src/node/hello::']
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)

  def test_lint_failure(self):
    command = ['lint',
               'contrib/node/exaamples/src/node/hello-test::']
    pants_run = self.run_pants(command=command)

    self.assert_failure(pants_run)