# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.java.jar.jar_dependency import JarDependency
from pants_test.test_base import TestBase


class UnpackedJarsTest(TestBase):

  def test_empty_libraries(self):
    with self.assertRaises(UnpackedJars.ExpectedLibrariesError):
      self.make_target(':foo', UnpackedJars)

  def test_simple(self):
    self.make_target(':import_jars', JarLibrary, jars=[JarDependency('foo', 'bar', '123')])
    target = self.make_target(':foo', UnpackedJars, libraries=[':import_jars'])

    self.assertIsInstance(target, UnpackedJars)
    dependency_specs = [spec for spec in target.compute_dependency_specs(payload=target.payload)]
    self.assertSequenceEqual([':import_jars'], dependency_specs)
    self.assertEqual(1, len(target.all_imported_jar_deps))
    import_jar_dep = target.all_imported_jar_deps[0]
    self.assertIsInstance(import_jar_dep, JarDependency)

  def test_bad_libraries_ref(self):
    self.make_target(':right-type', JarLibrary, jars=[JarDependency('foo', 'bar', '123')])
    self.make_target(':wrong-type', UnpackedJars, libraries=[':right-type'])
    target = self.make_target(':foo', UnpackedJars, libraries=[':wrong-type'])
    with self.assertRaises(ImportJarsMixin.WrongTargetTypeError):
      target.imported_targets
