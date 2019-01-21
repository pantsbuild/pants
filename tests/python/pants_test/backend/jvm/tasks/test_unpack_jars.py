# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

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
from pants.task.unpack_remote_sources_base import UnpackedArchives
from pants.util.collections import assert_single_element
from pants.util.contextutil import open_zip, temporary_dir
from pants_test.task_test_base import TaskTestBase


class UnpackJarsTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return UnpackJars

  @contextmanager
  def sample_jarfile(self, name):
    with temporary_dir() as temp_dir:
      jar_name = os.path.join(temp_dir, '{}.jar'.format(name))
      with open_zip(jar_name, 'w') as proto_jarfile:
        proto_jarfile.writestr('a/b/c/{}.txt'.format(name), 'Some text')
        proto_jarfile.writestr('a/b/c/{}.proto'.format(name), 'message Msg {}')
      yield jar_name

  def test_invalid_pattern(self):
    with self.assertRaises(UnpackJars.InvalidPatternError):
      UnpackJars.compile_patterns([45])

  @staticmethod
  def _run_filter(filename, include_patterns=None, exclude_patterns=None):
    return UnpackJars._file_filter(
      filename,
      UnpackJars.compile_patterns(include_patterns or []),
      UnpackJars.compile_patterns(exclude_patterns or []))

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

  def _make_unpacked_jar(self, coord, include_patterns, intransitive=False):
    jarlib = self._make_jar_library(coord)
    return self.make_target(spec='unpack:foo',
                            target_type=UnpackedJars,
                            libraries=[jarlib.address.spec],
                            include_patterns=include_patterns,
                            intransitive=intransitive)

  def test_unpack_jar_fingerprint_strategy(self):
    fingerprint_strategy = UnpackJarsFingerprintStrategy()

    make_unpacked_jar = functools.partial(self._make_unpacked_jar, include_patterns=['bar'])
    rev1 = M2Coordinate(org='com.example', name='bar', rev='0.0.1')
    target = make_unpacked_jar(rev1)
    fingerprint1 = fingerprint_strategy.compute_fingerprint(target)

    # Now, replace the build file with a different version.
    self.reset_build_graph()
    target = make_unpacked_jar(M2Coordinate(org='com.example', name='bar', rev='0.0.2'))
    fingerprint2 = fingerprint_strategy.compute_fingerprint(target)
    self.assertNotEqual(fingerprint1, fingerprint2)

    # Go back to the original library.
    self.reset_build_graph()
    target = make_unpacked_jar(rev1)
    fingerprint3 = fingerprint_strategy.compute_fingerprint(target)

    self.assertEqual(fingerprint1, fingerprint3)

  @staticmethod
  def _add_dummy_product(context, foo_target, jar_filename, coord):
    jar_import_products = context.products.get_data(JarImportProducts, init_func=JarImportProducts)
    jar_import_products.imported(foo_target, coord, jar_filename)

  def _do_test_products(self, intransitive):
    self.maxDiff = None
    with self.sample_jarfile('foo') as foo_jar:
      with self.sample_jarfile('bar') as bar_jar:
        foo_coords = M2Coordinate(org='com.example', name='foo', rev='0.0.1')
        bar_coords = M2Coordinate(org='com.example', name='bar', rev='0.0.7')
        unpacked_jar_tgt = self._make_unpacked_jar(
          foo_coords, include_patterns=['a/b/c/*.proto'], intransitive=intransitive)

        context = self.context(target_roots=[unpacked_jar_tgt])
        unpack_task = self.create_task(context)
        self._add_dummy_product(context, unpacked_jar_tgt, foo_jar, foo_coords)
        # We add jar_bar as a product against foo_tgt, to simulate it being an
        # externally-resolved dependency of jar_foo.
        self._add_dummy_product(context, unpacked_jar_tgt, bar_jar, bar_coords)
        unpack_task.execute()

        expected_files = {'a/b/c/foo.proto'}
        if not intransitive:
          expected_files.add('a/b/c/bar.proto')

        with unpack_task.invalidated([unpacked_jar_tgt]) as invalidation_check:
          vt = assert_single_element(invalidation_check.all_vts)
          self.assertEqual(vt.target, unpacked_jar_tgt)
          archives = context.products.get_data(UnpackedArchives, dict)[vt.target]
          self.assertEqual(expected_files, set(archives.found_files))

  def test_transitive(self):
    self._do_test_products(intransitive=False)

  def test_intransitive(self):
    self._do_test_products(intransitive=True)
