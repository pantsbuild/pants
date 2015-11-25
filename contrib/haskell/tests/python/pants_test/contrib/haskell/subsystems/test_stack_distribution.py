# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.util.contextutil import environment_as
from pants_test.subsystem.subsystem_util import subsystem_instance

from pants.contrib.haskell.subsystems.stack_distribution import StackDistribution


class StackDistributionTest(unittest.TestCase):

  @contextmanager
  def distribution(self):
    with subsystem_instance(StackDistribution.Factory) as factory:
      yield factory.create()

  def test_bootstrap(self):
    with self.distribution() as stack_distribution:
      stack_cmd = stack_distribution.create_stack_cmd(cmd='--numeric-version')
      output = stack_cmd.check_output()

      self.assertEqual(stack_distribution.version, output.strip())

  def assert_stack_root(self):
    with self.distribution() as stack_distribution:
      stack_cmd = stack_distribution.create_stack_cmd(cmd='path', cmd_args=['--global-stack-root'])

      self.assertIn('STACK_ROOT', stack_cmd.env)
      expected_stack_root = stack_cmd.env['STACK_ROOT']
      self.assertNotEqual(os.path.expanduser(os.path.join('~', '.stack')),
                          expected_stack_root)

      output = stack_cmd.check_output()

      self.assertEqual(expected_stack_root, output.strip())

  def test_stack_command_stack_root(self):
    self.assert_stack_root()

  def test_stack_command_stack_root_overrides_user_stack_root(self):
    with environment_as(STACK_ROOT='/dev/null'):
      self.assert_stack_root()
