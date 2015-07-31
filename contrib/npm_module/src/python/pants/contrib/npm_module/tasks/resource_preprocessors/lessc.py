# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.resource_preprocessor import ResourcePreprocessor

from pants.util.dirutil import safe_mkdir


class LessC(ResourcePreprocessor):
  """
    This Task downloads the lessc module specified and runs the less compiler
    on the lessc files speficed in the input target.
  """

  MODULE_VERSION = '1.5.1'
  MODULE_EXECUTABLE = os.path.join('bin', 'lessc')
  MODULE_NAME = 'less'

  @classmethod
  def product_types(cls):
    return ['less_css']

  def __init__(self, *args, **kwargs):
    super(LessC, self).__init__(*args, **kwargs)

  def execute_cmd(self, target, node_environ):
    files = set()
    safe_mkdir(os.path.join(self.workdir, target.gen_resource_path))
    for file in target.sources_relative_to_buildroot():
      source_file = os.path.join(self.buildroot, file)
      (file_name, ext) = os.path.splitext(os.path.basename(file))
      if ext == '.less':
        dest_file = os.path.join(target.gen_resource_path, '{0}.css'.format(file_name))
        cmd = [self.module_executable, source_file, '-x', os.path.join(self.workdir,
                                                              dest_file)]
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
    return GenResources.LESSC

