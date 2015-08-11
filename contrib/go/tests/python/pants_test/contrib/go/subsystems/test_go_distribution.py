# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import unittest

from pants.base.build_environment import get_pants_cachedir
from pants.binaries.binary_util import BinaryUtil

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoDistributionTest(unittest.TestCase):
  def setUp(self):
    # TODO(John Sirois): Learn create_subsystem how to handle subsystem dependencies and do:
    #   `create_subsystem(GoDistribution.Factory)`
    # Instead of manually replicating default subsystem options here.
    binary_util = BinaryUtil(baseurls=['https://dl.bintray.com/pantsbuild/bin/build-support'],
                             timeout_secs=30,
                             bootstrapdir=get_pants_cachedir())
    self.go_distribution = GoDistribution(binary_util, 'bin/go', '1.4.2')

  def test_bootstrap(self):
    go_cmd = self.go_distribution.create_go_cmd(cmd='env', args=['GOROOT'])
    process = go_cmd.spawn(stdout=subprocess.PIPE)
    stdout, _ = process.communicate()

    self.assertEqual(0, process.returncode)
    self.assertEqual(self.go_distribution.goroot, stdout.strip())

  def test_go_command_no_gopath(self):
    go_cmd = self.go_distribution.create_go_cmd(cmd='env', args=['GOROOT'])

    self.assertEqual({'GOROOT': self.go_distribution.goroot}, go_cmd.env)
    self.assertEqual('go', os.path.basename(go_cmd.cmdline[0]))
    self.assertEqual(['env', 'GOROOT'], go_cmd.cmdline[1:])
    self.assertRegexpMatches(str(go_cmd), r'^GOROOT=[^ ]+ .*/go env GOROOT$')

  def test_go_command_gopath(self):
    go_cmd = self.go_distribution.create_go_cmd(cmd='env', gopath='/tmp/fred', args=['GOROOT'])

    self.assertEqual({'GOROOT': self.go_distribution.goroot,
                      'GOPATH': '/tmp/fred'}, go_cmd.env)
    self.assertEqual('go', os.path.basename(go_cmd.cmdline[0]))
    self.assertEqual(['env', 'GOROOT'], go_cmd.cmdline[1:])
    self.assertRegexpMatches(str(go_cmd), r'^GOROOT=[^ ]+ GOPATH=/tmp/fred .*/go env GOROOT$')
