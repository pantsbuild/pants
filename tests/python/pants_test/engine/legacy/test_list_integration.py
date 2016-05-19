# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DependenciesIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
  def assert_list_new_equals_old(self, success, spec):
    self.assertEqual(
      self.run_regular_list(spec, success),
      self.run_engine_list(spec, success),
    )

  def run_engine_list(self, spec, success):
    args = ['-q', 'run', 'src/python/pants/engine/legacy:list', '--'] + spec
    return self.get_target_set(args, success)

  def run_regular_list(self, spec, success):
    args = ['-q', 'list'] + spec
    return self.get_target_set(args, success)

  def get_target_set(self, args, success):
    pants_run = self.run_pants(args)
    if success:
      self.assert_success(pants_run)
      stdout_lines = pants_run.stdout_data.split('\n')
      return sorted([l for l in stdout_lines if l])
    else:
      self.assert_failure(pants_run)
      return None

  def test_list_single(self):
    self.assert_list_new_equals_old(True, ['3rdparty::'])

  def test_list_multiple(self):
    self.assert_list_new_equals_old(
      True,
      ['3rdparty::', 'examples/src/::', 'testprojects/tests/::']
    )
