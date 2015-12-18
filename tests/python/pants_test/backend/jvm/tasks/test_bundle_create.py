# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.util.contextutil import open_zip
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase


class TestBundleCreate(JvmBinaryTaskTestBase):

  @classmethod
  def task_type(cls):
    return BundleCreate

  def setUp(self):
    super(TestBundleCreate, self).setUp()

    self.jar_artifact = self.create_artifact(org='org.example', name='foo', rev='1.0.0')
    self.zip_artifact = self.create_artifact(org='org.pantsbuild', name='bar', rev='2.0.0',
                                             ext='zip')
    self.bundle_artifact = self.create_artifact(org='org.apache', name='baz', rev='3.0.0',
                                                classifier='tests')
    self.tar_gz_artifact = self.create_artifact(org='org.gnu', name='gary', rev='4.0.0',
                                                ext='tar.gz')

    self.jar_lib = self.make_target(spec='3rdparty/jvm/org/example:foo',
                                    target_type=JarLibrary,
                                    jars=[JarDependency(org='org.example', name='foo', rev='1.0.0'),
                                          JarDependency(org='org.pantsbuild', name='bar', rev='2.0.0',
                                                        ext='zip'),
                                          JarDependency(org='org.apache', name='baz', rev='3.0.0',
                                                        classifier='tests'),
                                          JarDependency(org='org.gnu', name='gary', rev='4.0.0',
                                                        ext='tar.gz')])
    self.binary_target = self.make_target(spec='//foo:foo-binary',
                                          target_type=JvmBinary,
                                          source='Foo.java',
                                          dependencies=[self.jar_lib])
    self.app_target = self.make_target(spec='//foo:foo-app',
                                        target_type=JvmApp,
                                        basename='FooApp',
                                        dependencies=[self.binary_target])

    self.task_context = self.context(target_roots=[self.app_target])
    self._setup_classpath(self.task_context)

  def _setup_classpath(self, task_context):
    classpath_products = self.ensure_classpath_products(task_context)
    classpath_products.add_jars_for_targets(targets=[self.jar_lib],
                                            conf='default',
                                            resolved_jars=[self.jar_artifact,
                                                           self.zip_artifact,
                                                           self.bundle_artifact,
                                                           self.tar_gz_artifact])

    self.add_to_runtime_classpath(task_context, self.binary_target,
                                  {'Foo.class': '', 'foo.txt': ''})

  def test_jvm_bundle_products(self):
    self.execute(self.task_context)
    self.check_bundle_products('foo.foo-app')

  def test_jvm_bundle_use_basename(self):
    self.set_options(use_basename=True)
    self.task_context = self.context(target_roots=[self.app_target])
    self._setup_classpath(self.task_context)
    self.execute(self.task_context)
    self.check_bundle_products('FooApp')

  def check_bundle_products(self, bundle_basename):
    products = self.task_context.products.get('jvm_bundles')
    self.assertIsNotNone(products)
    product_data = products.get(self.app_target)
    dist_root = os.path.join(self.build_root, 'dist')
    self.assertEquals({dist_root: ['{basename}-bundle'.format(basename=bundle_basename)]},
                      product_data)

    bundle_root = os.path.join(dist_root, '{basename}-bundle'.format(basename=bundle_basename))
    # TODO foo.txt and Foo.class are also under libs in a subdirectory, verify their existence
    self.assertEqual(sorted(['foo-binary.jar',
                             'libs/org.example-foo-1.0.0.jar',
                             'libs/org.pantsbuild-bar-2.0.0.zip',
                             'libs/org.apache-baz-3.0.0-tests.jar',
                             'libs/org.gnu-gary-4.0.0.tar.gz']),
                     sorted(self.iter_files(bundle_root)))

    # TODO verify Manifest's Class-Path
    with open_zip(os.path.join(bundle_root, 'foo-binary.jar')) as jar:
      self.assertEqual(sorted(['META-INF/', 'META-INF/MANIFEST.MF']),
                       sorted(jar.namelist()))

  def test_jvm_bundle_missing_product(self):
    missing_jar_artifact = self.create_artifact(org='org.example', name='foo', rev='2.0.0',
                                                materialize=False)
    classpath_products = self.ensure_classpath_products(self.task_context)
    classpath_products.add_jars_for_targets(targets=[self.binary_target],
                                            conf='default',
                                            resolved_jars=[missing_jar_artifact])

    with self.assertRaises(BundleCreate.MissingJarError):
      self.execute(self.task_context)
