# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.base.exceptions import TaskError
from pants_test.base_test import BaseTest


def resolved_example_jar_at(path, org='com.example', name='lib'):
  return ResolvedJar(M2Coordinate(org=org, name=name),
                     cache_path=path,
                     path=path)

class ClasspathProductsTest(BaseTest):
  def test_single_classpath_element_no_excludes(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts()
    path = os.path.join(self.build_root, 'jar/path')
    self.add_jar_classpath_element_for_path(classpath_product, a, path)

    self.assertEqual([('default', path)], classpath_product.get_for_target(a))

  def test_fails_if_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts()
    with self.assertRaises(TaskError) as cm:
      classpath_product.add_for_target(a, [('default', '/dev/null')])

    self.assertEqual(
      'Classpath entry /dev/null for target a:a is located outside the buildroot.',
      str(cm.exception))

  def test_fails_if_jar_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts()
    with self.assertRaises(TaskError) as cm:
      classpath_product.add_jars_for_targets([a], 'default', [(resolved_example_jar_at('/dev/null'))])

    self.assertEqual(
      'Classpath entry /dev/null for target a:a is located outside the buildroot.',
      str(cm.exception))


  def test_excluded_classpath_element(self):
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    example_jar_path = self._example_jar_path()
    self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_transitive_dependencys_excluded_classpath_element(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts()
    self.add_jar_classpath_element_for_path(classpath_product, a, self._example_jar_path())
    self.add_excludes_for_targets(classpath_product, b, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_parent_exclude_excludes_dependency_jar(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    example_jar_path = self._example_jar_path()
    self.add_jar_classpath_element_for_path(classpath_product, b, example_jar_path)
    self.add_excludes_for_targets(classpath_product, b, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_exclude_leaves_other_jars_unaffected(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts()
    com_example_jar_path = self._example_jar_path()
    org_example_jar_path = os.path.join(self.build_root, 'ivy/jars/org.example/lib/123.4.jar')
    classpath_product.add_jars_for_targets([a], 'default',
                                          [resolved_example_jar_at(com_example_jar_path),
                                           resolved_example_jar_at(org_example_jar_path,
                                                                   org='org.example')])
    self.add_excludes_for_targets(classpath_product, b)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([('default', org_example_jar_path)], classpath)

  def test_parent_excludes_ignored_for_resolving_child_target(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    example_jar_path = self._example_jar_path()
    classpath_product = ClasspathProducts()
    self.add_jar_classpath_element_for_path(classpath_product, b, example_jar_path)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(b)

    self.assertEqual([('default', example_jar_path)], classpath)

  def test_excludes_used_across_targets(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts()
    self.add_example_jar_classpath_element_for(classpath_product, b)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_excludes_similar_org_name(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.exam')], dependencies=[b])

    classpath_product = ClasspathProducts()
    self.add_example_jar_classpath_element_for(classpath_product, b)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([('default', self._example_jar_path())], classpath)

  def test_excludes_org_name(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example')], dependencies=[b])

    classpath_product = ClasspathProducts()
    self.add_example_jar_classpath_element_for(classpath_product, b)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_jar_provided_by_transitive_target_excluded(self):
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example', 'lib', Repository()))
    consumer = self.make_target('consumer', JvmTarget)
    root = self.make_target('root', JvmTarget, dependencies=[provider, consumer])

    classpath_product = ClasspathProducts()
    self.add_example_jar_classpath_element_for(classpath_product, consumer)
    self.add_excludes_for_targets(classpath_product, consumer, provider, root)

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([], classpath)

  def test_jar_provided_exclude_with_similar_name(self):
    # note exclude 'jars/com.example/l' should not match jars/com.example/lib/jars/123.4.jar
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example', 'li', Repository()))
    root = self.make_target('root', JvmTarget, dependencies=[provider])

    classpath_product = ClasspathProducts()
    self.add_example_jar_classpath_element_for(classpath_product, root)
    self.add_excludes_for_targets(classpath_product, provider, root)

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([('default', self._example_jar_path())], classpath)

  def test_jar_provided_exclude_with_similar_org(self):
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example.lib', '', Repository()))
    root = self.make_target('root', JvmTarget, dependencies=[provider])

    classpath_product = ClasspathProducts()
    self.add_example_jar_classpath_element_for(classpath_product, root)
    self.add_excludes_for_targets(classpath_product, provider, root)

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([('default', self._example_jar_path())], classpath)

  def test_jar_in_classpath_not_a_resolved_jar_ignored_by_excludes(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example')], dependencies=[b])

    example_jar_path = self._example_jar_path()

    classpath_product = ClasspathProducts()
    classpath_product.add_for_target(b, [('default', example_jar_path)])
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([('default', example_jar_path)], classpath)

  def _example_jar_path(self):
    return os.path.join(self.build_root, 'ivy/jars/com.example/lib/jars/123.4.jar')

  def add_jar_classpath_element_for_path(self, classpath_product, target, example_jar_path):
    classpath_product.add_jars_for_targets([target], 'default', [resolved_example_jar_at(example_jar_path)])

  def add_excludes_for_targets(self, classpath_product, *targets):
    classpath_product.add_excludes_for_targets(targets)

  def add_example_jar_classpath_element_for(self, classpath_product, target):
    self.add_jar_classpath_element_for_path(classpath_product, target, self._example_jar_path())