# import os
from textwrap import dedent

# from pants.backend.codegen.thrift.lib.thrift import Thrift
from pants.contrib.node.tasks.apache_thrift_node_gen import ApacheThriftNodeGen
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants.contrib.node.targets.node_module import NodeModule
from pants_test.task_test_base import TaskTestBase


class ApacheThriftNodeGenTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ApacheThriftNodeGen

  def generate_single_thrift_target(self, node_thrift_library):
    context = self.context(target_roots=[node_thrift_library])
    apache_thrift_gen = self.create_task(context)
    apache_thrift_gen.execute()
    # import pdb; pdb.set_trace()

    def is_synthetic_node_library(target):
      return isinstance(target, NodeModule) and target.is_synthetic

    synthetic_targets = context.targets(predicate=is_synthetic_node_library)

    self.assertEqual(1, len(synthetic_targets))
    return synthetic_targets[0]

  def test_single_namespace(self):
    self.create_file('src/thrift/com/foo/test.thrift', contents=dedent("""
    namespace js foo.bar

    struct Test {}
    """))
    test = self.make_target(spec='src/thrift/com/foo:one',
                            target_type=NodeThriftLibrary,
                            sources=['test.thrift'])
    synthetic_target = self.generate_single_thrift_target(test)
    self.assertEqual({'package.json',
                      'yarn.lock',
                      'test_types.js'},
                     set(synthetic_target.sources_relative_to_source_root()))

  def test_nested_namespace(self):
    self.create_file('src/thrift/com/foo/test1.thrift', contents=dedent("""
    namespace js foo.bar

    struct Test1 {}
    """))
    self.create_file('src/thrift/com/foo/test2.thrift', contents=dedent("""
    namespace js foo.bar

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
                     set(synthetic_target.sources_relative_to_source_root()))
