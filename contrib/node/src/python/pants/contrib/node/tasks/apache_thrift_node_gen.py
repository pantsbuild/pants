import os
import json
from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.util.dirutil import safe_file_dump
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants.contrib.node.targets.node_module import NodeModule


class ApacheThriftNodeGen(ApacheThriftGenBase):
  """Generate Nodejs source files from thrift IDL files"""
  gentarget_type = NodeThriftLibrary
  thrift_generator = 'js:node'
  gen_directory = 'nodejs'

  _COMPILER = 'thrift'

  sources_globs = ('**/*',)


  def synthetic_target_type(self, target):
    return NodeModule

  @property
  def _copy_target_attributes(self):
    return ['tags', 'scope']
  

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
    sources_list = target.sources_relative_to_target_base()
    if 'yarn.lock' not in sources_list.files:
      safe_file_dump(os.path.join(target_workdir, 'yarn.lock'))
    
    if 'package.json' not in sources_list.files:
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
        with open(os.path.join(target_workdir, 'package.json'), 'w') as f:
            json.dump(package_dict, f, ensure_ascii=False, indent=2)

    super().execute_codegen(target, target_workdir)
