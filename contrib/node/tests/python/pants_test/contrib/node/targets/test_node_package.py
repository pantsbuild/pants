# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.base_test import BaseTest

from pants.contrib.node.targets.node_package import NodePackage


class NodePackageTest(BaseTest):
  def test_implicit_package_name(self):
    target = self.make_target(spec=':name', target_type=NodePackage)
    self.assertEqual('name', target.address.target_name)
    self.assertEqual('name', target.package_name)

  def test_explicit_package_name(self):
    target1 = self.make_target(spec=':name', target_type=NodePackage)
    target2 = self.make_target(spec=':name2', target_type=NodePackage, package_name='name')
    self.assertNotEqual(target1, target2)
    self.assertEqual('name', target1.address.target_name)
    self.assertEqual('name', target1.package_name)
    self.assertEqual('name2', target2.address.target_name)
    self.assertEqual('name', target2.package_name)
