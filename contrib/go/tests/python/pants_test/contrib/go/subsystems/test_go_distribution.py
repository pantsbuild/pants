# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import unittest

from pants.util.contextutil import environment_as
from pants_test.subsystem.subsystem_util import global_subsystem_instance

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoDistributionTest(unittest.TestCase):

  def distribution(self):
    factory = global_subsystem_instance(GoDistribution.Factory)
    return factory.create()

  def test_bootstrap(self):
    go_distribution = self.distribution()
    go_cmd = go_distribution.create_go_cmd(cmd='env', args=['GOROOT'])
    output = go_cmd.check_output()
    self.assertEqual(go_distribution.goroot, output.strip())

  def assert_no_gopath(self):
    go_distribution = self.distribution()

    go_env = go_distribution.go_env()

    # As of go 1.8, when GOPATH is unset (set to ''), it defaults to ~/go (assuming HOME is set -
    # and we can't unset that since it might legitmately be used by the subcommand) - so we manually
    # fetch the "unset" default value here as our expected value for tests below.
    # The key thing to note here is this default value is used only when `gopath` passed to
    # `GoDistribution` is None, implying the command to be run does not need or use a GOPATH.
    cmd = [os.path.join(go_distribution.goroot, 'bin', 'go'), 'env', 'GOPATH']
    env = os.environ.copy()
    env.update(go_env)
    default_gopath = subprocess.check_output(cmd, env=env).strip()

    go_cmd = go_distribution.create_go_cmd(cmd='env', args=['GOPATH'])

    self.assertEqual(go_env, go_cmd.env)
    self.assertEqual('go', os.path.basename(go_cmd.cmdline[0]))
    self.assertEqual(['env', 'GOPATH'], go_cmd.cmdline[1:])
    self.assertRegexpMatches(str(go_cmd),
                             r'^GOROOT=[^ ]+ GOPATH={} .*/go env GOPATH'.format(default_gopath))
    self.assertEqual(default_gopath, go_cmd.check_output().strip())

  def test_go_command_no_gopath(self):
    self.assert_no_gopath()

  def test_go_command_no_gopath_overrides_user_gopath_issue2321(self):
    # Without proper GOPATH scrubbing, this bogus entry leads to a `go env` failure as explained
    # here: https://github.com/pantsbuild/pants/issues/2321
    # Before that fix, the `go env` command would raise.
    with environment_as(GOPATH=':/bogus/first/entry'):
      self.assert_no_gopath()

  def test_go_command_gopath(self):
    go_distribution = self.distribution()
    go_cmd = go_distribution.create_go_cmd(cmd='env', gopath='/tmp/fred', args=['GOROOT'])

    self.assertEqual({'GOROOT': go_distribution.goroot,
                      'GOPATH': '/tmp/fred'}, go_cmd.env)
    self.assertEqual('go', os.path.basename(go_cmd.cmdline[0]))
    self.assertEqual(['env', 'GOROOT'], go_cmd.cmdline[1:])
    self.assertRegexpMatches(str(go_cmd), r'^GOROOT=[^ ]+ GOPATH=/tmp/fred .*/go env GOROOT$')
