# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.tasks.apache_thrift_gen import ApacheThriftGen
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants_test.tasks.task_test_base import TaskTestBase


class ApacheThriftGenTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ApacheThriftGen

  def setUp(self):
    super(ApacheThriftGenTest, self).setUp()

  def generate_single_thrift_target(self, java_thrift_library):
    context = self.context(target_roots=[java_thrift_library])
    apache_thrift_gen = self.create_task(context)
    apache_thrift_gen.execute()

    def is_synthetic_java_library(target):
      return isinstance(target, JavaLibrary) and target.is_synthetic
    synthetic_targets = context.targets(predicate=is_synthetic_java_library)

    self.assertEqual(1, len(synthetic_targets))
    return synthetic_targets[0]

  def test_single_namespace(self):
    self.create_file('src/thrift/com/foo/one.thrift', contents=dedent("""
    namespace java com.foo

    struct One {}
    """))
    one = self.make_target(spec='src/thrift/com/foo:one',
                           target_type=JavaThriftLibrary,
                           sources=['one.thrift'],
                           compiler='thrift')
    synthetic_target = self.generate_single_thrift_target(one)
    self.assertEqual(['com/foo/One.java'], list(synthetic_target.sources_relative_to_source_root()))

  def test_nested_namespaces(self):
    self.create_file('src/thrift/com/foo/one.thrift', contents=dedent("""
    namespace java com.foo

    struct One {}
    """))
    self.create_file('src/thrift/com/foo/bar/two.thrift', contents=dedent("""
    namespace java com.foo.bar

    struct Two {}
    """))
    one = self.make_target(spec='src/thrift/com/foo:one',
                           target_type=JavaThriftLibrary,
                           sources=['one.thrift', 'bar/two.thrift'],
                           compiler='thrift')
    synthetic_target = self.generate_single_thrift_target(one)
    self.assertEqual(sorted(['com/foo/One.java', 'com/foo/bar/Two.java']),
                     sorted(synthetic_target.sources_relative_to_source_root()))
