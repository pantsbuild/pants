# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ListOwnersIntegrationTest(PantsRunIntegrationTest):
  # TODO: This test provides additional coverage for list-owners, which is already covered by
  # unit tests. Unfortunately, those are not covering the v2 engine:
  #  see: https://github.com/pantsbuild/pants/issues/4401

  def get_target_set(self, std_out):
    return sorted([l for l in std_out.split('\n') if l])

  def targets_for(self, *args):
    return self.get_target_set(self.do_command(*args, success=True).stdout_data)

  def test_list_owners(self):
    targets = self.targets_for('list-owners', '--', 'contrib/go/examples/src/go/server/main.go')
    self.assertEqual(['contrib/go/examples/src/go/server:server'], targets)
