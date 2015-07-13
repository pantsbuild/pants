import os

from pants.util.dirutil import safe_mkdir
from twitter.common.util.command_util import CommandUtil

from pants.contrib.npm_module.tasks.resource_preprocessors.npm_module_base import NpmModuleBase
from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.resource_preprocessor import ResourcePreprocessor




class RTL(ResourcePreprocessor, NpmModuleBase):
  """
    This Task downloads the RTL module and performs the RTL transformations in the .css files
    listed in the input target.
  """

  MODULE_NAME = 'R2'
  MODULE_VERSION = '1.3.1'
  MODULE_EXECUTABLE = os.path.join('bin', 'r2')

  @classmethod
  def product_types(cls):
    return ['resources']

  @classmethod
  def prepare(cls, options, round_manager):
    super(RTL, cls).prepare(options, round_manager)
    round_manager.require_data('rtl')

  def __init__(self, *args, **kwargs):
    super(RTL, self).__init__(*args, **kwargs)
    # NodeJs RTL module does not provide a -v or -h flag to bootstrap the tool
    # Hence skipping bootstrap.
    self._skip_bootstrap = True

  def execute_cmd(self, target):
    bin = os.path.join(self.cachedir, self.MODULE_EXECUTABLE)
    files = set()
    safe_mkdir(os.path.join(self.workdir, target.gen_resource_path))
    for source_file in target.sources_relative_to_buildroot():
      source_file = os.path.join(self.buildroot, source_file)
      (file_name, ext) = os.path.splitext(os.path.basename(source_file))
      if (ext == '.css'):
        dest_file = os.path.join(target.gen_resource_path, '%s.rtl.css' % file_name)
        cmd = [bin, '%s' % source_file, '%s' % os.path.join(self.workdir, dest_file)]
        CommandUtil.execute_suppress_stdout(cmd)
        files.add(dest_file)
    return files

  def run_processor(self, target):
    return self.execute_npm_module(target)

  @property
  def processor_name(self):
    return GenResources.RTL
