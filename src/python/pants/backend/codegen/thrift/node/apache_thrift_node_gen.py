import os
from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary


class ApacheThriftNodeGen(ApacheThriftGenBase):
	"""Generate Nodejs source files from thrift IDL files"""
	gentarget_type = NodeThriftLibrary
	thrift_generator = 'nodejs'
	default_gen_options_map = {
		'new_style'
	}