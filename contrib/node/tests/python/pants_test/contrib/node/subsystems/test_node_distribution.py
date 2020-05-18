# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess
import unittest

from pants.testutil.subsystem.util import global_subsystem_instance

from pants.contrib.node.subsystems.node_distribution import NodeDistribution


class NodeDistributionTest(unittest.TestCase):
    def setUp(self):
        self.distribution = global_subsystem_instance(NodeDistribution)

    def test_bootstrap(self):
        node_cmd = self.distribution.node_command(args=["--version"])
        output = node_cmd.check_output().strip()
        self.assertEqual(self.distribution.version(), output)

    def test_node(self):
        node_command = self.distribution.node_command(
            args=["--interactive"]
        )  # Force a REPL session.
        repl = node_command.run(
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        out, err = repl.communicate(b'console.log("Hello World!")')
        self.assertEqual(b"", err)
        self.assertEqual(0, repl.returncode)

        for line in out.splitlines():
            if line.endswith(b"Hello World!"):
                break
        else:
            self.fail(
                f'Did not find the expected "Hello World!" in the REPL session output:\n{out.decode()}'
            )

    def test_npm(self):
        npm_version_flag = self.distribution.get_package_manager("npm").run_command(
            args=["--version"]
        )
        raw_version = npm_version_flag.check_output().strip()

        npm_version_cmd = self.distribution.get_package_manager("npm").run_command(
            args=["version", "--json"]
        )
        versions_json = npm_version_cmd.check_output()
        versions = json.loads(versions_json)

        self.assertEqual(raw_version, versions["npm"])

    def test_yarnpkg(self):
        yarnpkg_version_command = self.distribution.get_package_manager("yarn").run_command(
            args=["--version"]
        )
        yarnpkg_version = yarnpkg_version_command.check_output().strip()
        yarnpkg_versions_command = self.distribution.get_package_manager("yarn").run_command(
            args=["versions", "--json"]
        )
        yarnpkg_versions = json.loads(yarnpkg_versions_command.check_output())
        self.assertEqual(yarnpkg_version, yarnpkg_versions["data"]["yarn"])

    def test_node_command_path_injection(self):
        node_path_cmd = self.distribution.node_command(
            args=["--eval", 'console.log(process.env["PATH"])']
        )
        node_bin_path = self.distribution._install_node()

        # Test the case in which we do not pass in env,
        # which should fall back to env=os.environ.copy()
        injected_paths = node_path_cmd.check_output().strip().split(os.pathsep)
        self.assertEqual(node_bin_path, injected_paths[0])

    def test_node_command_path_injection_with_overridden_path(self):
        node_path_cmd = self.distribution.node_command(
            args=["--eval", 'console.log(process.env["PATH"])']
        )
        node_bin_path = self.distribution._install_node()
        injected_paths = (
            node_path_cmd.check_output(env={"PATH": "/test/path"}).strip().split(os.pathsep)
        )
        self.assertEqual(node_bin_path, injected_paths[0])
        self.assertListEqual([node_bin_path, "/test/path"], injected_paths)

    def test_node_command_path_injection_with_empty_path(self):
        node_path_cmd = self.distribution.node_command(
            args=["--eval", 'console.log(process.env["PATH"])']
        )
        node_bin_path = self.distribution._install_node()
        injected_paths = node_path_cmd.check_output(env={"PATH": ""}).strip().split(os.pathsep)
        self.assertListEqual([node_bin_path, ""], injected_paths)
