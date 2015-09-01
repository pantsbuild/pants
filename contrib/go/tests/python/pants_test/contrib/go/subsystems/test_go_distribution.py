# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants_test.subsystem.subsystem_util import subsystem_instance

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoDistributionTest(unittest.TestCase):

  @contextmanager
  def distribution(self):
    with subsystem_instance(GoDistribution.Factory) as factory:
      yield factory.create()

  def test_bootstrap(self):
    with self.distribution() as go_distribution:
      go_cmd = go_distribution.create_go_cmd(cmd='env', args=['GOROOT'])
      output = go_cmd.check_output()
      self.assertEqual(go_distribution.goroot, output.strip())

  def test_go_command_no_gopath(self):
    with self.distribution() as go_distribution:
      go_cmd = go_distribution.create_go_cmd(cmd='env', args=['GOROOT'])

      self.assertEqual({'GOROOT': go_distribution.goroot}, go_cmd.env)
      self.assertEqual('go', os.path.basename(go_cmd.cmdline[0]))
      self.assertEqual(['env', 'GOROOT'], go_cmd.cmdline[1:])
      self.assertRegexpMatches(str(go_cmd), r'^GOROOT=[^ ]+ .*/go env GOROOT$')

  def test_go_command_gopath(self):
    with self.distribution() as go_distribution:
      go_cmd = go_distribution.create_go_cmd(cmd='env', gopath='/tmp/fred', args=['GOROOT'])

      self.assertEqual({'GOROOT': go_distribution.goroot,
                        'GOPATH': '/tmp/fred'}, go_cmd.env)
      self.assertEqual('go', os.path.basename(go_cmd.cmdline[0]))
      self.assertEqual(['env', 'GOROOT'], go_cmd.cmdline[1:])
      self.assertRegexpMatches(str(go_cmd), r'^GOROOT=[^ ]+ GOPATH=/tmp/fred .*/go env GOROOT$')
