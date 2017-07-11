# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import unittest
from contextlib import contextmanager

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.backend.jvm.tasks.unpack_jars import UnpackJars, UnpackJarsFingerprintStrategy
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.util.contextutil import open_zip, temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.tasks.task_test_base import TaskTestBase


class UnpackJarsTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return UnpackJars

  @contextmanager
  def sample_jarfile(self):
    """Create a jar file with a/b/c/data.txt and a/b/c/foo.proto"""
    with temporary_dir() as temp_dir:
      jar_name = os.path.join(temp_dir, 'foo.jar')
      with open_zip(jar_name, 'w') as proto_jarfile:
        proto_jarfile.writestr('a/b/c/data.txt', 'Foo text')
        proto_jarfile.writestr('a/b/c/foo.proto', 'message Foo {}')
      yield jar_name

  def test_invalid_pattern(self):
    with self.assertRaises(UnpackJars.InvalidPatternError):
      UnpackJars._compile_patterns([45])

  def _run_filter(self, filename, include_patterns=None, exclude_patterns=None):
    return UnpackJars._file_filter(
      filename,
      UnpackJars._compile_patterns(include_patterns or []),
      UnpackJars._compile_patterns(exclude_patterns or []))

  def test_file_filter(self):
    # If no patterns are specified, everything goes through
    self.assertTrue(self._run_filter("foo/bar.java"))

    self.assertTrue(self._run_filter("foo/bar.java", include_patterns=["**/*.java"]))
    self.assertTrue(self._run_filter("bar.java", include_patterns=["**/*.java"]))
    self.assertTrue(self._run_filter("bar.java", include_patterns=["**/*.java", "*.java"]))
    self.assertFalse(self._run_filter("foo/bar.java", exclude_patterns=["**/bar.*"]))
    self.assertFalse(self._run_filter("foo/bar.java",
                                      include_patterns=["**/*/java"],
                                      exclude_patterns=["**/bar.*"]))

    # exclude patterns should be computed before include patterns
    self.assertFalse(self._run_filter("foo/bar.java",
                                      include_patterns=["foo/*.java"],
                                      exclude_patterns=["foo/b*.java"]))
    self.assertTrue(self._run_filter("foo/bar.java",
                                     include_patterns=["foo/*.java"],
                                     exclude_patterns=["foo/x*.java"]))

  @unittest.expectedFailure
  def test_problematic_cases(self):
    """These should pass, but don't"""
    # See https://github.com/twitter/commons/issues/380.  'foo*bar' doesn't match 'foobar'
    self.assertFalse(self._run_filter("foo/bar.java",
                                      include_patterns=['foo/*.java'],
                                      exclude_patterns=['foo/bar*.java']))

  def _make_jar_library(self, coord):
    return self.make_target(spec='unpack/jars:foo-jars',
                            target_type=JarLibrary,
                            jars=[JarDependency(org=coord.org, name=coord.name, rev=coord.rev,
                                                url='file:///foo.jar')])

  def _make_unpacked_jar(self, coord, include_patterns):
    bar = self._make_jar_library(coord)
    return self.make_target(spec='unpack:foo',
                            target_type=UnpackedJars,
                            libraries=[bar.address.spec],
                            include_patterns=include_patterns)

  def _make_coord(self, rev):
    return M2Coordinate(org='com.example', name='bar', rev=rev)

  def test_unpack_jar_fingerprint_strategy(self):
    fingerprint_strategy = UnpackJarsFingerprintStrategy()

    make_unpacked_jar = functools.partial(self._make_unpacked_jar, include_patterns=['bar'])
    rev1 = self._make_coord(rev='0.0.1')
    target = make_unpacked_jar(rev1)
    fingerprint1 = fingerprint_strategy.compute_fingerprint(target)

    # Now, replace the build file with a different version
    self.reset_build_graph()
    target = make_unpacked_jar(self._make_coord(rev='0.0.2'))
    fingerprint2 = fingerprint_strategy.compute_fingerprint(target)
    self.assertNotEqual(fingerprint1, fingerprint2)

    # Go back to the original library
    self.reset_build_graph()
    target = make_unpacked_jar(rev1)
    fingerprint3 = fingerprint_strategy.compute_fingerprint(target)

    self.assertEqual(fingerprint1, fingerprint3)

  def _add_dummy_product(self, unpack_task, foo_target, jar_filename, coord):
    jar_import_products = unpack_task.context.products.get_data(JarImportProducts,
                                                                init_func=JarImportProducts)
    jar_import_products.imported(foo_target, coord, jar_filename)

  def test_incremental(self):
    make_unpacked_jar = functools.partial(self._make_unpacked_jar,
                                          include_patterns=['a/b/c/*.proto'])

    with self.sample_jarfile() as jar_filename:
      rev1 = self._make_coord(rev='0.0.1')
      foo_target = make_unpacked_jar(rev1)

      # The first time through, the target should be unpacked.
      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      self._add_dummy_product(unpack_task, foo_target, jar_filename, rev1)
      unpacked_targets = unpack_task.execute()

      self.assertEquals([foo_target], unpacked_targets)
      unpack_dir = unpack_task._unpack_dir(foo_target)
      files = []
      for _, dirname, filenames in safe_walk(unpack_dir):
        files += filenames
      self.assertEquals(['foo.proto'], files)

      # Calling the task a second time should not need to unpack any targets
      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      self._add_dummy_product(unpack_task, foo_target, jar_filename, rev1)
      unpacked_targets = unpack_task.execute()

      self.assertEquals([], unpacked_targets)

      # Change the library version and the target should be unpacked again.
      self.reset_build_graph()  # Forget about the old definition of the unpack/jars:foo-jar target
      rev2 = self._make_coord(rev='0.0.2')
      foo_target = make_unpacked_jar(rev2)

      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      self._add_dummy_product(unpack_task, foo_target, jar_filename, rev2)
      unpacked_targets = unpack_task.execute()

      self.assertEquals([foo_target], unpacked_targets)

      # Change the include pattern and the target should be unpacked again
      self.reset_build_graph()  # Forget about the old definition of the unpack/jars:foo-jar target

      make_unpacked_jar = functools.partial(self._make_unpacked_jar,
                                            include_patterns=['a/b/c/foo.proto'])
      foo_target = make_unpacked_jar(rev2)
      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      self._add_dummy_product(unpack_task, foo_target, jar_filename, rev2)
      unpacked_targets = unpack_task.execute()

      self.assertEquals([foo_target], unpacked_targets)

      # TODO(Eric Ayers) Check the 'unpacked_archives' product
