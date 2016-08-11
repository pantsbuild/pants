# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class WhatChangedIntegrationTest(PantsRunIntegrationTest):

  def run_engine(self, success, *args):
    return self.do_command(*args, success=success, enable_v2_engine=True).stdout_data

  def run_regular(self, success, *args):
    return self.do_command(*args, success=success, enable_v2_engine=False).stdout_data

  def assert_changed_new_equals_old(self, changed_arguments):
    self.assert_run_new_equals_old(['-q', 'changed'] + changed_arguments, success=True)

  def assert_run_new_equals_old(self, args, success):
    self.assertEqual(
      self.run_regular(success, *args),
      self.run_engine(success, *args),
    )

  def test_changed(self):
    self.assert_changed_new_equals_old([])

  def test_changed_with_changes_since(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^'])
