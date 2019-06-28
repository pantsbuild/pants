import os
from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants.contrib.node.targets.node_module import NodeModule


class ApacheThriftNodeGen(ApacheThriftGenBase):
	"""Generate Nodejs source files from thrift IDL files"""
	gentarget_type = NodeThriftLibrary
	thrift_generator = 'nodejs'

	_COMPILER = 'thrift'


	def synthetic_target_type(self, target):
		return NodeModule


	def execute_codegen(selt, target, target_workdir):
 		thrift_target_deps = target.closure(lambda t: isinstance(t, ThriftTargetMixin))
 		all_thrift_sources = [
 		  s
 		  for s in t.sources_relative_to_buildroot()
 		  for t in thrift_target_deps
 		]
		super().execute_codegen(target, target_workdir, extra_sources)