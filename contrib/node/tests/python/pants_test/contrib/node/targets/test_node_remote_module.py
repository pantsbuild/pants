# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.base_test import BaseTest

from pants.contrib.node.targets.node_remote_module import NodeRemoteModule


class NodeRemoteModuleTest(BaseTest):
  def test_unconstrained(self):
    target1 = self.make_target(spec=':unconstrained1', target_type=NodeRemoteModule)
    target2 = self.make_target(spec=':unconstrained2', target_type=NodeRemoteModule, version=None)
    target3 = self.make_target(spec=':unconstrained3', target_type=NodeRemoteModule, version='')
    target4 = self.make_target(spec=':unconstrained4', target_type=NodeRemoteModule, version='*')

    self.assertEqual('*', target1.version)
    self.assertEqual('*', target2.version)
    self.assertEqual('*', target3.version)
    self.assertEqual('*', target4.version)

  def test_constrained(self):
    target1 = self.make_target(spec=':unconstrained1',
                               target_type=NodeRemoteModule,
                               package_name='asdf',
                               version='http://asdf.com/asdf.tar.gz#2.0.0')
    self.assertEqual('asdf', target1.package_name)
    self.assertEqual('http://asdf.com/asdf.tar.gz#2.0.0', target1.version)
