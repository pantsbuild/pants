import os
import shutil

from twitter.common.util.command_util import CommandUtil

from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir

from pants.contrib.npm_module.tasks.resource_preprocessors.npm_module_base import NpmModuleBase
from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.resource_preprocessor import ResourcePreprocessor


class RequireJS(ResourcePreprocessor, NpmModuleBase):
  """
    This Task downloads the requirejs module specified and performs the transformations
    specified by the config file --compile-requirejs-build-profile option.
  """

  MODULE_NAME = 'requirejs'
  MODULE_VERSION = '2.1.9'
  MODULE_EXECUTABLE = os.path.join('bin', 'r.js')

  @classmethod
  def product_types(cls):
    return ['resources']

  def execute_cmd(self, target):
    if len(target.sources_relative_to_buildroot()) > 1:
      raise TaskError('RequireJs processor takes one build profile file per target.')
    build_profile = os.path.join(self.buildroot, target.sources_relative_to_buildroot()[0])
    cmd = [self.bin_path, '-o', '%s' % build_profile]
    CommandUtil.execute_suppress_stdout(cmd)

    files = set()
    generated_js_dir = os.path.join(os.path.dirname(build_profile), target.gen_resource_path)
    dest_dir = os.path.join(self.workdir, target.gen_resource_path)
    safe_mkdir(dest_dir)
    for file in os.listdir(generated_js_dir):
      if not file.endswith('min.js') and file.endswith('.js'):
        #Copy the file to workdir at expected resource path.
        source_file = os.path.join(generated_js_dir, file)
        dest_file = os.path.join(dest_dir, file)
        shutil.copyfile(source_file, dest_file)
        resource_path = os.path.join(target.gen_resource_path, file)
        files.add(resource_path)
    return files

  def run_processor(self, target):
    return self.execute_npm_module(target)

  @property
  def processor_name(self):
    return GenResources.REQUIRE_JS
