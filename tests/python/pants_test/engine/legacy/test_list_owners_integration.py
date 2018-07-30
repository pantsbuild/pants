# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ListOwnersIntegrationTest(PantsRunIntegrationTest):
  def get_target_set(self, std_out):
    return sorted([l for l in std_out.split('\n') if l])

  def targets_for(self, *args):
    return self.get_target_set(self.do_command(*args, success=True).stdout_data)

  def test_list_owners(self):
    targets = self.targets_for('--owner-of=contrib/go/examples/src/go/server/main.go', 'list')
    self.assertEqual(['contrib/go/examples/src/go/server:server'], targets)
