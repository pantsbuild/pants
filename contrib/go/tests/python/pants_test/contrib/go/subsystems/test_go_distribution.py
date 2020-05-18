# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import unittest

from pants.testutil.subsystem.util import global_subsystem_instance
from pants.util.contextutil import environment_as

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoDistributionTest(unittest.TestCase):
    @staticmethod
    def _generate_go_command_regex(gopath, final_value):
        goroot_env = r"GOROOT=[^ ]+"
        gopath_env = r"GOPATH={}".format(gopath)
        # order of env values varies by interpreter and platform
        env_values = r"({goroot_env} {gopath_env}|{gopath_env} {goroot_env})".format(
            goroot_env=goroot_env, gopath_env=gopath_env
        )
        return r"^{env_values} .*/go env {final_value}$".format(
            env_values=env_values, final_value=final_value
        )

    def distribution(self):
        return global_subsystem_instance(GoDistribution)

    def test_bootstrap(self):
        go_distribution = self.distribution()
        go_cmd = go_distribution.create_go_cmd(cmd="env", args=["GOROOT"])
        output = go_cmd.check_output().decode().strip()
        self.assertEqual(go_distribution.goroot, output)

    def assert_no_gopath(self):
        go_distribution = self.distribution()

        go_env = go_distribution.go_env()

        # As of go 1.8, when GOPATH is unset (set to ''), it defaults to ~/go (assuming HOME is set -
        # and we can't unset that since it might legitimately be used by the subcommand) - so we manually
        # fetch the "unset" default value here as our expected value for tests below.
        # The key thing to note here is this default value is used only when `gopath` passed to
        # `GoDistribution` is None, implying the command to be run does not need or use a GOPATH.
        cmd = [os.path.join(go_distribution.goroot, "bin", "go"), "env", "GOPATH"]
        env = os.environ.copy()
        env.update(go_env)
        default_gopath = subprocess.check_output(cmd, env=env).decode().strip()

        go_cmd = go_distribution.create_go_cmd(cmd="env", args=["GOPATH"])

        self.assertEqual(go_env, go_cmd.env)
        self.assertEqual("go", os.path.basename(go_cmd.cmdline[0]))
        self.assertEqual(["env", "GOPATH"], go_cmd.cmdline[1:])
        self.assertEqual(default_gopath, go_cmd.check_output().decode().strip())

        regex = GoDistributionTest._generate_go_command_regex(
            gopath=default_gopath, final_value="GOPATH"
        )
        self.assertRegex(str(go_cmd), regex)

    def test_go_command_no_gopath(self):
        self.assert_no_gopath()

    def test_go_command_no_gopath_overrides_user_gopath_issue2321(self):
        # Without proper GOPATH scrubbing, this bogus entry leads to a `go env` failure as explained
        # here: https://github.com/pantsbuild/pants/issues/2321
        # Before that fix, the `go env` command would raise.
        with environment_as(GOPATH=":/bogus/first/entry"):
            self.assert_no_gopath()

    def test_go_command_gopath(self):
        go_distribution = self.distribution()
        go_cmd = go_distribution.create_go_cmd(cmd="env", gopath="/tmp/fred", args=["GOROOT"])

        self.assertEqual({"GOROOT": go_distribution.goroot, "GOPATH": "/tmp/fred"}, go_cmd.env)
        self.assertEqual("go", os.path.basename(go_cmd.cmdline[0]))
        self.assertEqual(["env", "GOROOT"], go_cmd.cmdline[1:])

        regex = GoDistributionTest._generate_go_command_regex(
            gopath="/tmp/fred", final_value="GOROOT"
        )
        self.assertRegex(str(go_cmd), regex)
