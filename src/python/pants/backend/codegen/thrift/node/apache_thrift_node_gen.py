import os
import json
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

    # def _codegen(self, target, target_workdir, extra_sources=[]):

    #     super().execute_codegen(target, target_workdir)

    def execute_codegen(selt, target, target_workdir):
        """
        thrift_target_deps = target.closure(lambda t: isinstance(t, ThriftTargetMixin))
        all_thrift_sources = [
          s
          for s in t.sources_relative_to_buildroot()
          for t in thrift_target_deps
        ]
        """
        if not os.path.exists('yarn.lock'):
            with open('yarn.lock', 'w') as f:
                continue

        if not os.path.exists('package.json'):
            dependency_list = target.dependencies
            package_dict = {}
            package_dict["name"] = target.name
            package_dict["version"] = "0.0.1"
            dep_dict = {}
            for dep in dependency_list:
                if isinstance(dep, NodeModule):
                    dep_spec = dep.address.spec_path
                    relative_path = os.path.relpath(deo_spec, target_workdir)
                    relative_path = "file:" + relative_path
                    dep_dict[dep.name] = relative_path

            package_dict["dependencies"] = dep_dict
    

            '''target.sources_relative_to_buildroot()'''
            with open('package.json', 'w') as f:
                json.dump(package_dict, f, ensure_ascii=False, indent=2)

        super().execute_codegen(target, target_workdir)
