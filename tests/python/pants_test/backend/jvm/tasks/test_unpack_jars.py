# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.unpack_jars import UnpackJars, UnpackJarsFingerprintStrategy
from pants.base.build_file_aliases import BuildFileAliases
from pants.util.contextutil import open_zip, temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.tasks.task_test_base import TaskTestBase


class UnpackJarsTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return UnpackJars

  @property
  def alias_groups(self):
    return BuildFileAliases(
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

    self.assertTrue(self._run_filter("foo/bar.java",
                               include_patterns=["**/*.java"]))
    self.assertTrue(self._run_filter("bar.java",
                                include_patterns=["**/*.java"]))
    self.assertTrue(self._run_filter("bar.java",
                               include_patterns=["**/*.java", "*.java"]))
    self.assertFalse(self._run_filter("foo/bar.java",
                                exclude_patterns=["**/bar.*"]))
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

  @pytest.mark.xfail
  def test_problematic_cases(self):
    """These should pass, but don't"""
    # See https://github.com/twitter/commons/issues/380.  'foo*bar' doesn't match 'foobar'
    self.assertFalse(self._run_filter("foo/bar.java",
                                      include_patterns=['foo/*.java'],
                                      exclude_patterns=['foo/bar*.java']))

  def _make_jar_library(self, version):
    build_path = os.path.join(self.build_root, 'unpack', 'jars', 'BUILD')
    if os.path.exists(build_path):
      os.remove(build_path)
    self.add_to_build_file('unpack/jars', dedent('''
      jar_library(name='foo-jars',
        jars=[
          jar(org='com.example', name='bar', rev='{version}', url='file:///foo.jar'),
        ],
      )
    '''.format(version=version)))

  def test_unpack_jar_fingerprint_strategy(self):
    fingerprint_strategy = UnpackJarsFingerprintStrategy()

    self.add_to_build_file('unpack', dedent('''
      unpacked_jars(name='foo',
        libraries=['unpack/jars:foo-jars'],
        include_patterns=[
          'bar',
        ],
       )
       '''))

    self._make_jar_library('0.0.1')

    target = self.target("unpack:foo")
    fingerprint1 = fingerprint_strategy.compute_fingerprint(target)

    # Now, replace the build file with a different version
    self.reset_build_graph()
    self._make_jar_library('0.0.2')
    target = self.target("unpack:foo")
    fingerprint2 = fingerprint_strategy.compute_fingerprint(target)
    self.assertNotEqual(fingerprint1, fingerprint2)

    # Go back to the original library
    self.reset_build_graph()
    self._make_jar_library('0.0.1')
    target = self.target("unpack:foo")
    fingerprint3 = fingerprint_strategy.compute_fingerprint(target)

    self.assertEqual(fingerprint1, fingerprint3)

  def _add_dummy_product(self, foo_target, jar_filename, unpack_task):
    ivy_imports_product = unpack_task.context.products.get('ivy_imports')
    ivy_imports_product.add(foo_target, os.path.dirname(jar_filename),
                            [os.path.basename(jar_filename)])

  def test_incremental(self):
    with self.sample_jarfile() as jar_filename:
      self.add_to_build_file('unpack', dedent('''
        unpacked_jars(name='foo',
          libraries=['unpack/jars:foo-jars'],
          include_patterns=[
            'a/b/c/*.proto',
          ],
         )
        '''))
      self._make_jar_library('0.0.1')
      foo_target = self.target('unpack:foo')

      # The first time through, the target should be unpacked.
      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      self._add_dummy_product(foo_target, jar_filename, unpack_task)
      unpacked_targets = unpack_task.execute()

      self.assertEquals([foo_target], unpacked_targets)
      unpack_dir = unpack_task._unpack_dir(foo_target)
      files = []
      for _, dirname, filenames in safe_walk(unpack_dir):
        files += filenames
      self.assertEquals(['foo.proto'], files)

      # Calling the task a second time should not need to unpack any targets
      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      self._add_dummy_product(foo_target, jar_filename, unpack_task)
      unpacked_targets = unpack_task.execute()

      self.assertEquals([], unpacked_targets)

      # Change the library version and the target should be unpacked again.
      self._make_jar_library('0.0.2')
      self.reset_build_graph()  # Forget about the old definition of the unpack/jars:foo-jar target
      foo_target = self.target('unpack:foo')  # Re-inject the target
      self._add_dummy_product(foo_target, jar_filename, unpack_task)
      unpack_task = self.create_task(self.context(target_roots=[foo_target]))
      unpacked_targets = unpack_task.execute()

      self.assertEquals([foo_target], unpacked_targets)

      # TODO(Eric Ayers) Check the 'unpacked_archives' product
