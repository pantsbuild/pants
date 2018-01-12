# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.contrib.node.subsystems import tool_binaries


class FakeToolMixin(object):
  def _get_bin_dir(self):
    return 'fake_tool_bin_dir'


class FakeNodeBinary(FakeToolMixin, tool_binaries.NodeBinary):
  pass


class FakeYarnBinary(FakeToolMixin, tool_binaries.YarnBinary):
  pass


class FakeNpmBinary(FakeToolMixin, tool_binaries.NpmBinary):
  pass


class TestNpm(unittest.TestCase):
  node = FakeNodeBinary(None, 'node_support_dir', '1.0.0')
  npm = FakeNpmBinary(node)

  def test_install_package(self):
    command = self.npm.install_packages()
    self.assertEqual(
      command.cmd, ['fake_tool_bin_dir/npm', 'install', '--no-optional'])

  def test_install_package_all(self):
    command = self.npm.install_packages(install_optional=True)
    self.assertEqual(
      command.cmd, ['fake_tool_bin_dir/npm', 'install'])


class TestYarn(unittest.TestCase):
  node = FakeNodeBinary(None, 'node_support_dir', '1.0.0')
  yarn = FakeYarnBinary(None, 'yarn_support_dir', '1.0.0', node)

  def test_install_package(self):
    command = self.yarn.install_packages()
    self.assertEqual(
      command.cmd, ['fake_tool_bin_dir/yarnpkg', '--ignore-optional'])

  def test_install_package_all(self):
    command = self.yarn.install_packages(install_optional=True)
    self.assertEqual(
      command.cmd, ['fake_tool_bin_dir/yarnpkg'])
