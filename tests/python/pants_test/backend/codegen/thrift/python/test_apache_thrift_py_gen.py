# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

import six

from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants_test.tasks.task_test_base import TaskTestBase


class ApacheThriftPyGenTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ApacheThriftPyGen

  def generate_single_thrift_target(self, python_thrift_library):
    context = self.context(target_roots=[python_thrift_library])
    apache_thrift_gen = self.create_task(context)
    apache_thrift_gen.execute()

    def is_synthetic_python_library(target):
      return isinstance(target, PythonLibrary) and target.is_synthetic
    synthetic_targets = context.targets(predicate=is_synthetic_python_library)

    self.assertEqual(1, len(synthetic_targets))
    return synthetic_targets[0]

  def init_py_path(self, target, package_rel_dir):
    return os.path.join(self.build_root, target.target_base, package_rel_dir, '__init__.py')

  def assert_ns_package(self, target, package_rel_dir):
    with open(self.init_py_path(target, package_rel_dir)) as fp:
      self.assertEqual(b"__import__('pkg_resources').declare_namespace(__name__)",
                       fp.read().strip())

  def assert_leaf_package(self, target, package_rel_dir, *services):
    # We know thrift controls exported package symbols using `__all__`; so reading this out of the
    # `__init__.py` is enough to show we haven't trampled non-trivial thrift-generated `__init__.py`
    # files.

    symbols = {}
    with open(self.init_py_path(target, package_rel_dir), 'rb') as fp:
      six.exec_(fp.read(), symbols)

    self.assertIn('__all__', symbols)
    self.assertEqual(sorted(('constants', 'ttypes') + services), sorted(symbols['__all__']))

  def test_single_namespace(self):
    self.create_file('src/thrift/com/foo/one.thrift', contents=dedent("""
    namespace py foo.bar

    const i32 THINGCONSTANT = 42

    struct Thing {}

    service ThingService {}
    """))
    one = self.make_target(spec='src/thrift/com/foo:one',
                           target_type=PythonThriftLibrary,
                           sources=['one.thrift'])
    synthetic_target = self.generate_single_thrift_target(one)
    self.assertEqual({'foo/__init__.py',
                      'foo/bar/__init__.py',
                      'foo/bar/ThingService-remote',
                      'foo/bar/ThingService.py',
                      'foo/bar/ttypes.py',
                      'foo/bar/constants.py'},
                     set(synthetic_target.sources_relative_to_source_root()))
    self.assert_ns_package(synthetic_target, 'foo')
    self.assert_leaf_package(synthetic_target, 'foo/bar', 'ThingService')

  def test_nested_namespaces(self):
    self.create_file('src/thrift/com/foo/one.thrift', contents=dedent("""
    namespace py foo.bar

    struct One {}
    """))
    self.create_file('src/thrift/com/foo/bar/two.thrift', contents=dedent("""
    namespace py foo.bar.baz

    struct Two {}
    """))
    one = self.make_target(spec='src/thrift/com/foo:one',
                           target_type=PythonThriftLibrary,
                           sources=['one.thrift', 'bar/two.thrift'])
    synthetic_target = self.generate_single_thrift_target(one)
    self.assertEqual({'foo/__init__.py',
                      'foo/bar/__init__.py',
                      'foo/bar/constants.py',
                      'foo/bar/ttypes.py',
                      'foo/bar/baz/__init__.py',
                      'foo/bar/baz/constants.py',
                      'foo/bar/baz/ttypes.py'},
                     set(synthetic_target.sources_relative_to_source_root()))
    self.assert_ns_package(synthetic_target, 'foo')
    self.assert_leaf_package(synthetic_target, 'foo/bar')
    self.assert_leaf_package(synthetic_target, 'foo/bar/baz')
