# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants_test.task_test_base import TaskTestBase

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants.contrib.node.tasks.apache_thrift_node_gen import ApacheThriftNodeGen


class ApacheThriftNodeGenTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ApacheThriftNodeGen

  def generate_multiple_thrift_targets(self, node_thrift_library):
    context = self.context(target_roots=[node_thrift_library])
    apache_thrift_gen = self.create_task(context)
    apache_thrift_gen.execute()

    def is_synthetic_node_library(target):
      return isinstance(target, NodeModule) and target.is_synthetic

    synthetic_targets = context.targets(predicate=is_synthetic_node_library)

    self.assertNotEqual(0, len(synthetic_targets))
    return synthetic_targets

  def generate_single_thrift_target(self, node_thrift_library):
    context = self.context(target_roots=[node_thrift_library])
    apache_thrift_gen = self.create_task(context)
    apache_thrift_gen.execute()

    def is_synthetic_node_library(target):
      return isinstance(target, NodeModule) and target.is_synthetic

    synthetic_targets = context.targets(predicate=is_synthetic_node_library)

    self.assertEqual(1, len(synthetic_targets))
    return synthetic_targets[0]

  def test_single_namespace(self):
    self.create_file('src/thrift/com/foo/test.thrift', contents=dedent("""
    namespace js gen.foo.bar

    struct Test {}
    """))
    test = self.make_target(spec='src/thrift/com/foo:one',
                            target_type=NodeThriftLibrary,
                            sources=['test.thrift'])
    synthetic_target = self.generate_single_thrift_target(test)
    self.assertEqual({'package.json',
                      'yarn.lock',
                      'test_types.js'},
                     set(synthetic_target.sources_relative_to_target_base()))

  def test_nested_namespace(self):
    self.create_file('src/thrift/com/foo/test1.thrift', contents=dedent("""
    namespace js gen.foo.bar

    struct Test1 {}
    """))
    self.create_file('src/thrift/com/foo/test2.thrift', contents=dedent("""
    namespace js gen.foo.bar

    struct Test2 {}
    """))
    test1 = self.make_target(spec='src/thrift/com/foo:test1',
                             target_type=NodeThriftLibrary,
                             sources=['test1.thrift', 'test2.thrift'])
    synthetic_target = self.generate_single_thrift_target(test1)
    self.assertEqual({'package.json',
                      'yarn.lock',
                      'test1_types.js',
                      'test2_types.js'},
                     set(synthetic_target.sources_relative_to_target_base()))

  def test_namespace_effective(self):
    self.create_file('src/thrift/com/foo/test1.thrift', contents=dedent("""
    namespace js gen.foo.bar

    struct Test1 {}
    """))
    self.create_file('src/thrift/com/foo/test2.thrift', contents=dedent("""
    namespace js gen.foo.bar

    struct Test2 {}
    """))
    test1 = self.make_target(spec='src/thrift/com/foo:test1',
                             target_type=NodeThriftLibrary,
                             sources=['test1.thrift'])
    test2 = self.make_target(spec='src/thrift/com/foo:test2',
                             target_type=NodeThriftLibrary,
                             sources=['test2.thrift'])
    synthetic_target1 = self.generate_single_thrift_target(test1)
    synthetic_target2 = self.generate_single_thrift_target(test2)

    self.assertNotEqual(synthetic_target1, synthetic_target2)

  def test_thrift_target_dependable(self):
    self.create_file('src/thrift/com/foo/test1.thrift', contents=dedent("""
    namespace js gen.foo.bar

    struct Test1 {}
    """))
    test1 = self.make_target(spec='src/thrift/com/foo:test1',
                             target_type=NodeThriftLibrary,
                             sources=['test1.thrift'])

    self.create_file('src/thrift/com/foo/test2.thrift', contents=dedent("""
    namespace js gen.foo.bar
    include "test1.thrift"

    struct Test2 {
      1: required test1.Test1 test_obj;
    }
    """))

    test2 = self.make_target(spec='src/thrift/com/foo:test2',
                             target_type=NodeThriftLibrary,
                             sources=['test2.thrift'],
                             dependencies=[test1])
    synthetic_node_target1, synthetic_node_target2 = self.generate_multiple_thrift_targets(test2)

    self.assertEqual({'package.json',
                      'yarn.lock',
                      'test1_types.js'},
                     set(synthetic_node_target1.sources_relative_to_target_base()))

    self.assertEqual({'package.json',
                      'yarn.lock',
                      'test2_types.js'},
                     set(synthetic_node_target2.sources_relative_to_target_base()))
