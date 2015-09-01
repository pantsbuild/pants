# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import zipfile
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.ivy_imports import IvyImports
from pants.base.build_file_aliases import BuildFileAliases
from pants.util.contextutil import open_zip, temporary_dir
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class IvyImportsTest(NailgunTaskTestBase):

  @classmethod
  def task_type(cls):
    return IvyImports

  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'unpacked_jars': UnpackedJars,
        'jar_library': JarLibrary,
        'target': Dependencies
      },
      objects={
        'jar': JarDependency,
        },
      )

  @contextmanager
  def sample_jarfile(self, filename):
    """Create a jar file with a/b/c/data.txt and a/b/c/foo.proto"""
    with temporary_dir() as temp_dir:
      jar_name = os.path.join(temp_dir, filename)
      with open_zip(jar_name, 'w') as proto_jarfile:
        proto_jarfile.writestr('a/b/c/data.txt', 'Foo text')
        proto_jarfile.writestr('a/b/c/foo.proto', 'message Foo {}')
      yield jar_name

  def _make_jar_library(self, version, jar_filename):
    build_path = os.path.join(self.build_root, 'unpack', 'jars', 'BUILD')
    if os.path.exists(build_path):
      os.remove(build_path)
    self.add_to_build_file('unpack/jars', dedent('''
        jar_library(name='foo-jars',
          jars=[
            jar(org='com.example', name='bar', rev='{version}', url='file:///{jar_filename}'),
          ],
        )
      '''.format(version=version, jar_filename=jar_filename)))

  def test_incremental(self):
    with self.sample_jarfile('foo.jar') as jar_filename:
      self.add_to_build_file('unpack', dedent('''
              unpacked_jars(name='foo',
                libraries=['unpack/jars:foo-jars'],
                include_patterns=[
                  'a/b/c/*.proto',
                ],
               )
              '''))
      self._make_jar_library("0.0.1", jar_filename)
      foo_target = self.target('unpack:foo')

      def check_compile(expected_targets):
        self.set_options(use_nailgun=False)
        ivy_imports_task = self.create_task(self.context(target_roots=[foo_target]))
        imported_targets = ivy_imports_task.execute()

        self.assertEquals(expected_targets, imported_targets)
        # Make sure the product is properly populated
        ivy_imports_product = ivy_imports_task.context.products.get('ivy_imports')
        self.verify_product_mapping(ivy_imports_product, target=foo_target,
                                    org='com.example', name='bar', conf='default',
                                    expected_jar_filenames=['com.example-bar-0.0.1.jar'])

      # The first time through, the jar file should be mapped.
      check_compile([foo_target])

      # The second time through, it should be cached.  execute won't return any targets compiled
      # but should still populate the ivy_imports product by target.
      check_compile([])

  def verify_product_mapping(self, ivy_imports_product, target=None, org=None, name=None, conf=None,
      expected_jar_filenames=None):
    """Verify that the ivy_import_product is formatted correctly.

    What we care about for UnpackJars and ProtobufGen are the target => builddir mapping.

      UnpackedJars(BuildFileAddress(.../unpack/BUILD, foo)) =>
          <workdir>/mapped-jars/unpack.foo/com.example/bar/default
        [u'com.example-bar-0.0.1.jar']
    """
    symlinkdir_suffix = os.path.join('mapped-jars', target.id, org, name, conf)
    mapping = ivy_imports_product.get(target)
    found = False
    for (symlinkdir, jar_filenames) in mapping.iteritems():
      if symlinkdir.endswith(symlinkdir_suffix):
        found = True
        self.verify_product(expected_jar_filenames, symlinkdir, jar_filenames)
    self.assertTrue(found, msg='Could not find {0}'.format(symlinkdir_suffix))

  def verify_product(self, expected_jar_filenames, symlinkdir, jar_filenames):
    self.assertEquals(expected_jar_filenames, jar_filenames)
    for jar_filename in jar_filenames:
      symlink_path = os.path.join(symlinkdir, jar_filename)
      self.assertTrue(os.path.islink(symlink_path))
      # Make sure there is a real .jar there
      self.assertTrue(zipfile.is_zipfile(symlink_path))
