# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import subprocess
import unittest

from pants_test.subsystem.subsystem_util import global_subsystem_instance

from pants.contrib.node.subsystems.node_distribution import NodeDistribution


class NodeDistributionTest(unittest.TestCase):

  def setUp(self):
    self.distribution = global_subsystem_instance(NodeDistribution.Factory).create()

  def test_bootstrap(self):
    node_cmd = self.distribution.node_command(args=['--version'])
    output = node_cmd.check_output()
    self.assertEqual(self.distribution.version, output.strip())

  def test_node(self):
    node_command = self.distribution.node_command(args=['--interactive'])  # Force a REPL session.
    repl = node_command.run(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = repl.communicate('console.log("Hello World!")')
    self.assertEqual('', err)
    self.assertEqual(0, repl.returncode)

    for line in out.splitlines():
      if line.endswith('Hello World!'):
        break
    else:
      self.fail('Did not find the expected "Hello World!" in the REPL session '
                'output:\n{}'.format(out))

  def test_npm(self):
    npm_version_flag = self.distribution.npm_command(args=['--version'])
    raw_version = npm_version_flag.check_output().strip()

    npm_version_cmd = self.distribution.npm_command(args=['version', '--json'])
    versions_json = npm_version_cmd.check_output()
    versions = json.loads(versions_json)

    self.assertEqual(raw_version, versions['npm'])

  def test_yarnpkg(self):
    yarnpkg_version_command = self.distribution.yarnpkg_command(args=['--version'])
    yarnpkg_version = yarnpkg_version_command.check_output().strip()
    yarnpkg_versions_command = self.distribution.yarnpkg_command(args=['versions', '--json'])
    yarnpkg_versions = json.loads(yarnpkg_versions_command.check_output())
    self.assertEqual(yarnpkg_version, yarnpkg_versions['data']['yarn'])

  def test_node_command_path_injection(self):
    node_bin_path = self.distribution.install_node()
    node_path_cmd = self.distribution.node_command(
      args=['--eval', 'console.log(process.env["PATH"])'])

    # Test the case in which we do not pass in env,
    # which should fall back to env=os.environ.copy()
    injected_paths = node_path_cmd.check_output().strip().split(os.pathsep)
    self.assertEqual(node_bin_path, injected_paths[0])

  def test_node_command_path_injection_with_overrided_path(self):
    node_bin_path = self.distribution.install_node()
    node_path_cmd = self.distribution.node_command(
      args=['--eval', 'console.log(process.env["PATH"])'])
    injected_paths = node_path_cmd.check_output(
      env={'PATH': '/test/path'}
    ).strip().split(os.pathsep)
    self.assertEqual(node_bin_path, injected_paths[0])
    self.assertListEqual([node_bin_path, '/test/path'], injected_paths)

  def test_node_command_path_injection_with_empty_path(self):
    node_bin_path = self.distribution.install_node()
    node_path_cmd = self.distribution.node_command(
      args=['--eval', 'console.log(process.env["PATH"])'])
    injected_paths = node_path_cmd.check_output(
      env={'PATH': ''}
    ).strip().split(os.pathsep)
    self.assertListEqual([node_bin_path, ''], injected_paths)
