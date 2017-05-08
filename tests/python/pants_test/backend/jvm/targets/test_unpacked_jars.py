# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.java.jar.jar_dependency import JarDependency
from pants_test.base_test import BaseTest


class UnpackedJarsTest(BaseTest):

  def test_empty_libraries(self):
    with self.assertRaises(UnpackedJars.ExpectedLibrariesError):
      self.make_target(':foo', UnpackedJars)

  def test_simple(self):
    self.make_target(':import_jars', JarLibrary, jars=[JarDependency('foo', 'bar', '123')])
    target = self.make_target(':foo', UnpackedJars, libraries=[':import_jars'])

    self.assertIsInstance(target, UnpackedJars)
    dependency_specs = [spec for spec in target.compute_dependency_specs(payload=target.payload)]
    self.assertSequenceEqual([':import_jars'], dependency_specs)
    self.assertEquals(1, len(target.imported_jars))
    import_jar_dep = target.imported_jars[0]
    self.assertIsInstance(import_jar_dep, JarDependency)

  def test_bad_libraries_ref(self):
    self.make_target(':right-type', JarLibrary, jars=[JarDependency('foo', 'bar', '123')])
    self.make_target(':wrong-type', UnpackedJars, libraries=[':right-type'])
    target = self.make_target(':foo', UnpackedJars, libraries=[':wrong-type'])
    with self.assertRaises(ImportJarsMixin.ExpectedJarLibraryError):
      target.imported_jar_libraries
