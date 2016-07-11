# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.classpath_util import MissingClasspathEntryError
from pants.build_graph.resources import Resources
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_file_dump
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase


class TestBundleCreate(JvmBinaryTaskTestBase):

  @classmethod
  def task_type(cls):
    return BundleCreate

  def setUp(self):
    """Prepare targets, context, runtime classpath. """
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
                                          JarDependency(org='org.pantsbuild',
                                                        name='bar',
                                                        rev='2.0.0',
                                                        ext='zip'),
                                          JarDependency(org='org.apache', name='baz', rev='3.0.0',
                                                        classifier='tests'),
                                          JarDependency(org='org.gnu', name='gary', rev='4.0.0',
                                                        ext='tar.gz')])

    safe_file_dump(os.path.join(self.build_root, 'resources/foo/file'), '// dummy content')
    self.resources_target = self.make_target('//resources:foo-resources', Resources,
                                             sources=['foo/file'])

    # This is so that payload fingerprint can be computed.
    safe_file_dump(os.path.join(self.build_root, 'foo/Foo.java'), '// dummy content')
    self.java_lib_target = self.make_target('//foo:foo-library', JavaLibrary, sources=['Foo.java'])

    self.binary_target = self.make_target(spec='//foo:foo-binary',
                                          target_type=JvmBinary,
                                          dependencies=[self.java_lib_target, self.jar_lib],
                                          resources=[self.resources_target.address.spec])

    self.dist_root = os.path.join(self.build_root, 'dist')

  def _create_target(self, **kwargs):
    return self.make_target(spec='//foo:foo-app',
                            target_type=JvmApp,
                            basename='FooApp',
                            dependencies=[self.binary_target],
                            **kwargs)

  def _setup_classpath(self, task_context):
    """As a separate prep step because to test different option settings, this needs to rerun
    after context is re-created.
    """
    classpath_products = self.ensure_classpath_products(task_context)
    classpath_products.add_jars_for_targets(targets=[self.jar_lib],
                                            conf='default',
                                            resolved_jars=[self.jar_artifact,
                                                           self.zip_artifact,
                                                           self.bundle_artifact,
                                                           self.tar_gz_artifact])

    self.add_to_runtime_classpath(task_context, self.binary_target,
                                  {'Foo.class': '', 'foo.txt': '', 'foo/file': ''})

  def test_jvm_bundle_products(self):
    """Test default setting outputs bundle products using `target.id`."""
    self.app_target = self._create_target()
    self.task_context = self.context(target_roots=[self.app_target])
    self._setup_classpath(self.task_context)
    self.execute(self.task_context)
    self._check_bundle_products('foo.foo-app', check_symlink=True)

  def test_jvm_bundle_use_basename_prefix(self):
    """Test override default setting outputs bundle products using basename."""
    self.app_target = self._create_target()
    self.set_options(use_basename_prefix=True)
    self.task_context = self.context(target_roots=[self.app_target])
    self._setup_classpath(self.task_context)
    self.execute(self.task_context)
    self._check_bundle_products('foo.foo-app', check_symlink=True, symlink_name_prefix='FooApp')

  def test_bundle_non_app_target(self):
    """Test bundle does not apply to a non jvm_app/jvm_binary target."""
    self.task_context = self.context(target_roots=[self.java_lib_target])
    self._setup_classpath(self.task_context)
    self.execute(self.task_context)

    self.assertIsNone(self.task_context.products.get('jvm_bundles').get(self.java_lib_target))
    self.assertFalse(os.path.exists(self.dist_root))

  def test_jvm_bundle_missing_product(self):
    """Test exception is thrown in case of a missing jar."""
    self.app_target = self._create_target()
    self.task_context = self.context(target_roots=[self.app_target])
    missing_jar_artifact = self.create_artifact(org='org.example', name='foo', rev='2.0.0',
                                                materialize=False)
    classpath_products = self.ensure_classpath_products(self.task_context)
    classpath_products.add_jars_for_targets(targets=[self.binary_target],
                                            conf='default',
                                            resolved_jars=[missing_jar_artifact])

    with self.assertRaises(MissingClasspathEntryError):
      self.execute(self.task_context)

  def test_conflicting_basename(self):
    """Test exception is thrown when two targets share the same basename."""
    self.app_target = self._create_target()
    conflict_app_target = self.make_target(spec='//foo:foo-app-conflict',
                                           target_type=JvmApp,
                                           basename='FooApp',
                                           dependencies=[self.binary_target])
    self.set_options(use_basename_prefix=True)
    self.task_context = self.context(target_roots=[self.app_target, conflict_app_target])
    self._setup_classpath(self.task_context)
    with self.assertRaises(BundleCreate.BasenameConflictError):
      self.execute(self.task_context)

  def test_target_options(self):
    self.app_target = self._create_target(archive='zip')
    self.task_context = self.context(target_roots=[self.app_target])
    self._setup_classpath(self.task_context)
    self.execute(self.task_context)
    self._check_archive_products('foo.foo-app', 'zip', check_copy=True)

  def test_cli_suppress_target_options(self):
    self.set_options(archive='tar')
    self.app_target = self._create_target(archive='zip')
    self.task_context = self.context(target_roots=[self.app_target])
    self._setup_classpath(self.task_context)
    self.execute(self.task_context)
    self._check_archive_products('foo.foo-app', 'tar', check_copy=True)

  def _check_products(self, products, product_fullname):
    self.assertIsNotNone(products)
    product_data = products.get(self.app_target)
    product_basedir = product_data.keys()[0]
    self.assertIn(self.pants_workdir, product_basedir)
    self.assertEquals(product_data[product_basedir], [product_fullname])
    product_path = os.path.join(product_basedir, product_fullname)
    return product_path

  def _check_archive_products(self, archive_name_prefix, archive_extension, check_copy=False, copy_name_prefix=''):
    products = self.task_context.products.get('deployable_archives')
    archive_fullname = '{}.{}'.format(archive_name_prefix, archive_extension)
    archive_path = self._check_products(products, archive_fullname)
    self.assertTrue(os.path.isfile(archive_path))

    if check_copy:
      copy_fullname = '{}.{}'.format(copy_name_prefix, archive_extension) if copy_name_prefix else archive_fullname
      copy_path = os.path.join(self.dist_root, copy_fullname)
      self.assertTrue(os.path.isfile(copy_path))

  def _check_bundle_products(self, bundle_name_prefix, check_symlink=False, symlink_name_prefix=''):
    products = self.task_context.products.get('jvm_bundles')
    bundle_fullname = '{}-bundle'.format(bundle_name_prefix)
    bundle_root = self._check_products(products, bundle_fullname)
    self.assertTrue(os.path.isdir(bundle_root))

    self.assertEqual(sorted(['foo-binary.jar',
                             'libs/foo.foo-binary-0.jar',
                             'libs/3rdparty.jvm.org.example.foo-0.jar',
                             'libs/3rdparty.jvm.org.example.foo-1.zip',
                             'libs/3rdparty.jvm.org.example.foo-2.jar',
                             'libs/3rdparty.jvm.org.example.foo-3.gz']),
                     sorted(self.iter_files(bundle_root)))

    with open_zip(os.path.join(bundle_root, 'libs/foo.foo-binary-0.jar')) as zf:
      self.assertEqual(sorted(['META-INF/',
                               'META-INF/MANIFEST.MF',
                               'Foo.class',
                               'foo.txt',
                               'foo/',
                               'foo/file']),
                       sorted(zf.namelist()))

    # TODO verify Manifest's Class-Path
    with open_zip(os.path.join(bundle_root, 'foo-binary.jar')) as jar:
      self.assertEqual(sorted(['META-INF/', 'META-INF/MANIFEST.MF']),
                       sorted(jar.namelist()))

    # Check symlink.
    if check_symlink:
      symlink_fullname = '{}-bundle'.format(symlink_name_prefix) if symlink_name_prefix else bundle_fullname
      symlink_path = os.path.join(self.dist_root, symlink_fullname)
      self.assertTrue(os.path.islink(symlink_path))
      self.assertEqual(os.readlink(symlink_path), bundle_root)
