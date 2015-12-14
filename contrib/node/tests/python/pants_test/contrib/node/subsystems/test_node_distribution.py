# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import subprocess
import unittest
from contextlib import contextmanager

from pants_test.subsystem.subsystem_util import subsystem_instance

from pants.contrib.node.subsystems.node_distribution import NodeDistribution


class NodeDistributionTest(unittest.TestCase):

  @contextmanager
  def distribution(self):
    with subsystem_instance(NodeDistribution.Factory) as factory:
      yield factory.create()

  def test_bootstrap(self):
    with self.distribution() as node_distribution:
      node_cmd = node_distribution.node_command(args=['--version'])
      output = node_cmd.check_output()
      self.assertEqual(node_distribution.version, output.strip())

  def test_node(self):
    with self.distribution() as node_distribution:
      node_command = node_distribution.node_command(args=['--interactive'])  # Force a REPL session.
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
    with self.distribution() as node_distribution:
      npm_version_flag = node_distribution.npm_command(args=['--version'])
      raw_version = npm_version_flag.check_output().strip()

      npm_version_cmd = node_distribution.npm_command(args=['version', '--json'])
      versions_json = npm_version_cmd.check_output()
      versions = json.loads(versions_json)

      self.assertEqual(raw_version, versions['npm'])

  def test_bin_dir_on_path(self):
    with self.distribution() as node_distribution:
      node_cmd = node_distribution.node_command(args=['--eval', 'console.log(process.env["PATH"])'])

      # Test the case in which we do not pass in env,
      # which should fall back to env=os.environ.copy()
      output = node_cmd.check_output().strip()
      self.assertEqual(node_cmd.bin_dir_path, output.split(os.pathsep)[0])

      output = node_cmd.check_output(env={'PATH': '/test/path'}).strip()
      self.assertEqual(node_cmd.bin_dir_path + os.path.pathsep + '/test/path', output)

      output = node_cmd.check_output(env={'PATH': ''}).strip()
      self.assertEqual(node_cmd.bin_dir_path, output)
