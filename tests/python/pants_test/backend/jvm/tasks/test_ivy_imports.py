# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import zipfile
from contextlib import contextmanager

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.ivy_imports import IvyImports
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.util.contextutil import open_zip, temporary_dir
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class IvyImportsTest(NailgunTaskTestBase):

  @classmethod
  def task_type(cls):
    return IvyImports

  @contextmanager
  def sample_jarfile(self, filename):
    """Create a jar file with a/b/c/data.txt and a/b/c/foo.proto"""
    with temporary_dir() as temp_dir:
      jar_name = os.path.join(temp_dir, filename)
      with open_zip(jar_name, 'w') as proto_jarfile:
        proto_jarfile.writestr('a/b/c/data.txt', 'Foo text')
        proto_jarfile.writestr('a/b/c/foo.proto', 'message Foo {}')
      yield jar_name

  def _make_jar_library(self, coordinate, jar_filename):
    build_path = os.path.join(self.build_root, 'unpack', 'jars', 'BUILD')
    if os.path.exists(build_path):
      os.remove(build_path)
    return self.make_target(spec='unpack/jars:foo-jars',
                            target_type=JarLibrary,
                            jars=[JarDependency(coordinate.org, coordinate.name, coordinate.rev,
                                                url='file:{}'.format(jar_filename))])

  def test_products(self):
    expected_coordinate = M2Coordinate(org='com.example', name='bar', rev='0.0.1')
    with self.sample_jarfile('foo.jar') as jar_filename:
      jar_library = self._make_jar_library(expected_coordinate, jar_filename)
      foo_target = self.make_target(spec='unpack:foo',
                                    target_type=UnpackedJars,
                                    libraries=[jar_library.address.spec],
                                    include_patterns=['a/b/c/*.proto'])

      self.set_options(use_nailgun=False)
      ivy_imports_task = self.create_task(self.context(target_roots=[foo_target]))
      ivy_imports_task.execute()

      # Make sure the product is properly populated
      jar_import_products = ivy_imports_task.context.products.get_data(JarImportProducts)
      self.verify_product_mapping(jar_import_products,
                                  target=foo_target,
                                  expected_coordinate=expected_coordinate)

  def verify_product_mapping(self, jar_import_products, target, expected_coordinate):
    jars_by_coordinate = dict(jar_import_products.imports(target))
    self.assertIn(expected_coordinate, jars_by_coordinate)
    jar_filename = jars_by_coordinate[expected_coordinate]
    self.assertTrue(os.path.islink(jar_filename))
    # Make sure there is a real .jar there
    self.assertTrue(zipfile.is_zipfile(jar_filename))
