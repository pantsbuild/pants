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
      stack_cmd = stack_distribution.create_stack_cmd(cmd='--version')
      output = stack_cmd.check_output()

      # Stack version strings look like so:
      # Version 0.1.6.0, Git revision e22271f5ce9afa2cb5be3bad9cafa392c623f85c (2313 commits) x86_64
      self.assertIn('Version {},'.format(stack_distribution.version), output.strip())

  def assert_stack_root(self):
    with self.distribution() as stack_distribution:
      stack_cmd = stack_distribution.create_stack_cmd(cmd='env', args=['GOPATH'])

      self.assertIn('STACK_ROOT', stack_cmd.env)
      self.assertNotEqual(os.path.expanduser(os.path.join('~', '.stack')),
                          stack_cmd.env['STACK_ROOT'])

  def test_go_command_no_gopath(self):
    self.assert_stack_root()

  def test_stack_command_stack_root_overrides_user_stack_root(self):
    with environment_as(STACK_ROOT='/dev/null'):
      self.assert_stack_root()
