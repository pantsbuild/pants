import os

from pants.contrib.npm_module.tasks.resource_preprocessors.npm_module_base import NpmModuleBase

from twitter.common.util.command_util import CommandUtil
from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.resource_preprocessor import ResourcePreprocessor

from pants.util.dirutil import safe_mkdir


class LessC(ResourcePreprocessor, NpmModuleBase):
  """
    This Task downloads the lessc module specified and runs the less compiler
    on the lessc files speficed in the input target.
  """

  # TODO Move this as advanced options so that this is configurable
  MODULE_VERSION = '1.5.1'
  MODULE_NAME = 'lessc'
  MODULE_EXECUTABLE = os.path.join('bin', 'lessc')

  @classmethod
  def product_types(cls):
    return ['rtl']

  def __init__(self, *args, **kwargs):
    super(LessC, self).__init__(*args, **kwargs)

  def execute_cmd(self, target):
    files = set()
    safe_mkdir(os.path.join(self.workdir, target.gen_resource_path))
    for file in target.sources_relative_to_buildroot():
      source_file = os.path.join(self.buildroot, file)
      (file_name, ext) = os.path.splitext(os.path.basename(file))
      if ext == '.less':
        dest_file = os.path.join(target.gen_resource_path, '%s.css' % file_name)
        cmd = [self.bin_path, source_file, '-x', os.path.join(self.workdir,
                                                              dest_file)]
        CommandUtil.execute_suppress_stdout(cmd)
        files.add(dest_file)
    return files

  def run_processor(self, target):
    return self.execute_npm_module(target)

  @property
  def processor_name(self):
    return GenResources.LESSC

