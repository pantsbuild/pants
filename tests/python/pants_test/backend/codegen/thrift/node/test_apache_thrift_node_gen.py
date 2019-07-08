import os
from textwrap import dedent

from pants.backend.codegen.thrift.lib.thrift import Thrift
from pants.backend.codegen.thrift.python.apache_thrift_node_gen import ApacheThriftNodeGen
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants_test.task_test_base import TaskTestBase

class ApacheThriftNodeGenTest(TaskTestBase):

	@classmethod
	def tast_type(cls):
		return ApacheThriftNodeGen

  
	def generate_single_thrift_target(self, node_thrift_library):
		context = self.context(target_roots=[node_thrift_library])
		apache_thrift_gen = self.create_task(context)
		apache_thrift_gen.execute()

		def is_synthetic_node_library(target):
			return isinstance(target, NodeThriftLibrary) and target.is_synthetic
		synthetic_targets = context.targets(predicate=is_synthetic_node_library)

		self.assertEqual(1, len(synthetic_targets))
		return synthetic_targets[0]
