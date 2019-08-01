import os
import json
import re
from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.util.dirutil import safe_file_dump
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants.contrib.node.targets.node_module import NodeModule
from pants.build_graph.target import Target
from typing import List


class ApacheThriftNodeGen(ApacheThriftGenBase):
  """Generate Nodejs source files from thrift IDL files"""
  gentarget_type = NodeThriftLibrary
  thrift_generator = 'js:node'
  gen_directory = 'nodejs'

  _COMPILER = 'thrift'

  sources_globs = ('**/*',)

  def synthetic_target_type(self, target: Target) -> NodeModule:
    return NodeModule

  @property
  def _copy_target_attributes(self) -> List[str]:
    return ['tags', 'node_scope', 'package_manager', 'build_script',
            'output_dir', 'dev_dependency', 'style_ignore_path', 'bin_executables']

  def execute_codegen(selt, target, target_workdir):
    sources_list = target.sources_relative_to_target_base()
    if 'yarn.lock' not in sources_list.files:
      safe_file_dump(os.path.join(target_workdir, 'yarn.lock'))

    if 'package.json' not in sources_list.files:
      dependency_list = target.dependencies
      package_dict = {}
      package_dict["name"] = target.name
      package_dict["version"] = "0.0.1"
      main_name = os.path.basename(target.sources_relative_to_buildroot()[0])
      package_dict["main"] = re.sub(r'\.thrift', '_types.js', main_name)
      dep_dict = {}
      for dep in dependency_list:
        if not isinstance(dep, NodeModule):
          continue
        dep_spec = dep.address.spec_path
        relative_path = os.path.relpath(dep_spec, target_workdir)
        relative_path = "file:" + relative_path
        dep_dict[dep.name] = relative_path

      package_dict["dependencies"] = dep_dict
      with open(os.path.join(target_workdir, 'package.json'), 'w') as f:
        json.dump(package_dict, f, ensure_ascii=False, indent=2)

    super().execute_codegen(target, target_workdir)
