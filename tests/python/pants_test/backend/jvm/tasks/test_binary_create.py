# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.util.contextutil import open_zip
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase


class TestBinaryCreate(JvmBinaryTaskTestBase):

  @classmethod
  def task_type(cls):
    return BinaryCreate

  def test_jvm_binaries_products(self):
    binary_target = self.make_target(spec='//bar:bar-binary',
                                     target_type=JvmBinary,
                                     source='Bar.java')
    context = self.context(target_roots=[binary_target])
    classpath_products = self.ensure_classpath_products(context)

    jar_artifact = self.create_artifact(org='org.example', name='foo', rev='1.0.0')
    with open_zip(jar_artifact.pants_path, 'w') as jar:
      jar.writestr('foo/Foo.class', '')
    classpath_products.add_jars_for_targets(targets=[binary_target],
                                            conf='default',
                                            resolved_jars=[jar_artifact])

    self.add_to_runtime_classpath(context, binary_target, {'Bar.class': '', 'bar.txt': ''})

    self.execute(context)

    jvm_binary_products = context.products.get('jvm_binaries')
    self.assertIsNotNone(jvm_binary_products)
    product_data = jvm_binary_products.get(binary_target)
    dist_root = os.path.join(self.build_root, 'dist')
    self.assertEquals({dist_root: ['bar-binary.jar']}, product_data)

    with open_zip(os.path.join(dist_root, 'bar-binary.jar')) as jar:
      self.assertEqual(sorted(['META-INF/',
                               'META-INF/MANIFEST.MF',
                               'foo/',
                               'foo/Foo.class',
                               'Bar.class',
                               'bar.txt']),
                       sorted(jar.namelist()))

  def test_jvm_binaries_deploy_excludes(self):
    foo_jar_lib = self.make_target(spec='3rdparty/jvm/org/example:foo',
                                   target_type=JarLibrary,
                                   jars=[JarDependency(org='org.example', name='foo', rev='1.0.0')])
    binary_target = self.make_target(spec='//bar:bar-binary',
                                     target_type=JvmBinary,
                                     source='Bar.java',
                                     dependencies=[foo_jar_lib],
                                     deploy_excludes=[Exclude(org='org.pantsbuild')])
    context = self.context(target_roots=[binary_target])
    classpath_products = self.ensure_classpath_products(context)

    foo_artifact = self.create_artifact(org='org.example', name='foo', rev='1.0.0')
    with open_zip(foo_artifact.pants_path, 'w') as jar:
      jar.writestr('foo/Foo.class', '')

    baz_artifact = self.create_artifact(org='org.pantsbuild', name='baz', rev='2.0.0')
    with open_zip(baz_artifact.pants_path, 'w') as jar:
      # This file should not be included in the binary jar since org.pantsbuild is deploy excluded.
      jar.writestr('baz/Baz.class', '')

    classpath_products.add_jars_for_targets(targets=[foo_jar_lib],
                                            conf='default',
                                            resolved_jars=[foo_artifact, baz_artifact])

    self.add_to_runtime_classpath(context, binary_target, {'Bar.class': '', 'bar.txt': ''})

    self.execute(context)
    jvm_binary_products = context.products.get('jvm_binaries')
    self.assertIsNotNone(jvm_binary_products)
    product_data = jvm_binary_products.get(binary_target)
    dist_root = os.path.join(self.build_root, 'dist')
    self.assertEquals({dist_root: ['bar-binary.jar']}, product_data)

    with open_zip(os.path.join(dist_root, 'bar-binary.jar')) as jar:
      self.assertEqual(sorted(['META-INF/',
                               'META-INF/MANIFEST.MF',
                               'foo/',
                               'foo/Foo.class',
                               'Bar.class',
                               'bar.txt']),
                       sorted(jar.namelist()))
