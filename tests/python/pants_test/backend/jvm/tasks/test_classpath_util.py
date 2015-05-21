# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.exceptions import TaskError
from pants.goal.products import UnionProducts
from pants_test.base_test import BaseTest


class ClasspathUtilTest(BaseTest):
  def test_single_classpath_element_no_excludes(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = UnionProducts()
    path = os.path.join(self.build_root, 'jar/path')
    classpath_product.add_for_target(a, [('default', path)])
    classpath = ClasspathUtil.compute_classpath([a], classpath_product, [], ['default'])
    self.assertEqual([path], classpath)

  def test_fails_on_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = UnionProducts()
    classpath_product.add_for_target(a, [('default', '/dev/null')])

    with self.assertRaises(TaskError):
      ClasspathUtil.compute_classpath([a], classpath_product, [], ['default'])

  def test_excluded_classpath_element(self):
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = UnionProducts()
    example_jar_path = os.path.join(self.build_root, 'ivy/jars/com.example/lib/123.4.jar')
    classpath_product.add_for_target(a, [('default', example_jar_path)])

    classpath = ClasspathUtil.compute_classpath([a], classpath_product, [], ['default'])

    self.assertEqual([], classpath)

  def test_transitive_dependencys_excluded_classpath_element(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = UnionProducts()
    example_jar_path = os.path.join(self.build_root, 'ivy/jars/com.example/lib/123.4.jar')
    classpath_product.add_for_target(a, [('default', example_jar_path)])

    classpath = ClasspathUtil.compute_classpath([a], classpath_product, [], ['default'])

    self.assertEqual([], classpath)

  def test_exclude_leaves_other_jars_unaffected(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = UnionProducts()
    com_example_jar_path = os.path.join(self.build_root, 'ivy/jars/com.example/lib/123.4.jar')
    org_example_jar_path = os.path.join(self.build_root, 'ivy/jars/org.example/lib/123.4.jar')
    classpath_product.add_for_target(a, [('default', com_example_jar_path),
                                         ('default', org_example_jar_path)])

    classpath = ClasspathUtil.compute_classpath([a], classpath_product, [], ['default'])

    self.assertEqual([org_example_jar_path], classpath)

  def test_parent_excludes_ignored_for_resolving_child_target(self):
    b = self.make_target('b', JvmTarget)
    self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    classpath_product = UnionProducts()
    example_jar_path = os.path.join(self.build_root, 'ivy/jars/com.example/lib/123.4.jar')
    classpath_product.add_for_target(b, [('default', example_jar_path)])

    classpath = ClasspathUtil.compute_classpath([b], classpath_product, [], ['default'])

    self.assertEqual([example_jar_path], classpath)
