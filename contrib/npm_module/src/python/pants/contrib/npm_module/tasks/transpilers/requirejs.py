# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import subprocess

from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir

from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.transpiler import Transpiler


class RequireJS(Transpiler):
  """
    This Task downloads the requirejs module specified and performs the transformations
    specified by the config file --compile-requirejs-build-profile option.
  """

  MODULE_NAME = 'requirejs'
  MODULE_VERSION = '2.1.9'
  MODULE_EXECUTABLE = os.path.join('bin', 'r.js')

  def __init__(self, *args, **kwargs):
    super(RequireJS, self).__init__(*args, **kwargs)

  @classmethod
  def product_types(cls):
    return ['min_js']

  def execute_cmd(self, target, node_environ):
    if len(target.sources_relative_to_buildroot()) > 1:
      raise TaskError('RequireJs processor takes one build profile file per target.')
    build_profile = os.path.join(self.buildroot, target.sources_relative_to_buildroot()[0])
    cmd = [self.module_executable, '-o', '%s' % build_profile]
    self.context.log.debug('Executing: {0}\n'.format(' '.join(cmd)))
    process = subprocess.Popen(cmd, env=node_environ)
    result = process.wait()
    if result != 0:
      raise Transpiler.TranspilerError('{0} ... exited non-zero ({1})'
                                                           .format(self.module_name, result))

    files = set()
    generated_js_dir = os.path.join(os.path.dirname(build_profile), target.gen_resource_path)
    dest_dir = os.path.join(self.workdir, target.gen_resource_path)
    safe_mkdir(dest_dir)
    for file in os.listdir(generated_js_dir):
      if not file.endswith('min.js') and file.endswith('.js'):
        # Copy the file to workdir at expected resource path.
        source_file = os.path.join(generated_js_dir, file)
        dest_file = os.path.join(dest_dir, file)
        shutil.copyfile(source_file, dest_file)
        resource_path = os.path.join(target.gen_resource_path, file)
        files.add(resource_path)
    return files

  @property
  def transpiler_name(self):
    return GenResources.REQUIRE_JS
