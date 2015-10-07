# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NpmResolveIntegrationTest(PantsRunIntegrationTest):

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
