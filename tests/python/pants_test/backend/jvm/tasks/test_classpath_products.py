# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.base.exceptions import TaskError
from pants_test.base_test import BaseTest


class ClasspathProductsTest(BaseTest):
  def test_single_classpath_element_no_excludes(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts()
    path = os.path.join(self.build_root, 'jar/path')
    classpath_product.add_for_target(a, [('default', path)])

    self.assertEqual([('default', path)], classpath_product.get_for_target(a))

  def test_fails_if_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts()
    with self.assertRaises(TaskError) as cm:
        classpath_product.add_for_target(a, [('default', '/dev/null')])

    classpath = classpath_product.get_for_target(a)

    self.assertEqual(
      'Classpath entry /dev/null for target a:a is located outside the buildroot.',
      str(cm.exception))

  def test_excluded_classpath_element(self):
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    example_jar_path = self._example_jar_path()
    classpath_product.add_for_target(a, [('default', example_jar_path)])
    classpath_product.add_excludes_for_targets([a])

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_transitive_dependencys_excluded_classpath_element(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts()
    example_jar_path = self._example_jar_path()
    classpath_product.add_for_target(a, [('default', example_jar_path)])
    classpath_product.add_excludes_for_targets([a, b])

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_parent_exclude_excludes_dependency_jar(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    example_jar_path = self._example_jar_path()
    classpath_product.add_for_target(b, [('default', example_jar_path)])
    classpath_product.add_excludes_for_targets([a, b])

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_exclude_leaves_other_jars_unaffected(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts()
    com_example_jar_path = self._example_jar_path()
    org_example_jar_path = os.path.join(self.build_root, 'ivy/jars/org.example/lib/123.4.jar')
    classpath_product.add_for_target(a, [('default', com_example_jar_path),
                                         ('default', org_example_jar_path)])
    classpath_product.add_excludes_for_targets([b])

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([('default', org_example_jar_path)], classpath)

  def test_parent_excludes_ignored_for_resolving_child_target(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    example_jar_path = self._example_jar_path()
    classpath_product.add_for_target(b, [('default', example_jar_path)])
    classpath_product.add_excludes_for_targets([a])

    classpath = classpath_product.get_for_target(b)

    self.assertEqual([('default', example_jar_path)], classpath)

  def test_excludes_used_across_targets(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    classpath_product.add_for_target(b, [('default', self._example_jar_path())])
    classpath_product.add_excludes_for_targets([a])

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_jar_provided_by_transitive_target_excluded(self):
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example', 'lib', Repository()))
    consumer = self.make_target('consumer', JvmTarget)
    root = self.make_target('root', JvmTarget, dependencies=[provider])

    classpath_product = ClasspathProducts()
    classpath_product.add_for_target(consumer, [('default', self._example_jar_path())])
    classpath_product.add_excludes_for_targets([root, provider, consumer])

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([], classpath)

  def _example_jar_path(self):
    return os.path.join(self.build_root, 'ivy/jars/com.example/lib/123.4.jar')
