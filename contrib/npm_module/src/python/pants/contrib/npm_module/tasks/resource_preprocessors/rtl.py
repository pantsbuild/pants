import os
import subprocess

from pants.util.dirutil import safe_mkdir

from pants.contrib.npm_module.tasks.resource_preprocessors.npm_module_base import NpmModuleBase
from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.resource_preprocessor import ResourcePreprocessor


class RTL(ResourcePreprocessor, NpmModuleBase):
  """
    This Task downloads the RTL module and performs the RTL transformations in the .css files
    listed in the input target.
  """

  MODULE_NAME = 'R2'
  MODULE_EXECUTABLE = os.path.join('bin', 'r2')
  # TODO Move this as advanced options so that this is configurable
  MODULE_VERSION = '1.3.1'

  @classmethod
  def product_types(cls):
    return ['rtl_css']

  @classmethod
  def prepare(cls, options, round_manager):
    super(RTL, cls).prepare(options, round_manager)
    round_manager.require_data('less_css')

  def __init__(self, *args, **kwargs):
    super(RTL, self).__init__(*args, **kwargs)
    self._module_name = RTL.MODULE_NAME

  def execute_cmd(self, target, node_environ):
    bin = os.path.join(self.cachedir, self.MODULE_EXECUTABLE)
    files = set()
    safe_mkdir(os.path.join(self.workdir, target.gen_resource_path))
    for source_file in target.sources_relative_to_buildroot():
      source_file = os.path.join(self.buildroot, source_file)
      (file_name, ext) = os.path.splitext(os.path.basename(source_file))
      if (ext == '.css'):
        dest_file = os.path.join(target.gen_resource_path, '%s.rtl.css' % file_name)
        cmd = [bin, '%s' % source_file, '%s' % os.path.join(self.workdir, dest_file)]
        self.context.log.debug('Executing: {0}\n'.format(' '.join(cmd)))
        process = subprocess.Popen(cmd, env=node_environ)
        result = process.wait()
        if result != 0:
          raise ResourcePreprocessor.ResourcePreprocessorError('{0} ... exited non-zero ({1})'
                                                               .format(self.module_name, result))
        files.add(dest_file)
    return files

  def run_processor(self, target):
    return self.execute_npm_module(target)

  @property
  def processor_name(self):
    return GenResources.RTL
