# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from twitter.common import log

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.aapt_task import AaptTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir


class AaptBuilder(AaptTask):
  """Build an android bundle with compiled code and assets.

  This class gathers compiled classes (an Android dex archive) and packages it with the
  target's resource files. The output is an unsigned .apk, an Android application package file.
  """
  @classmethod
  def product_types(cls):
    return ['apk']

  @staticmethod
  def is_app(target):
    return isinstance(target, AndroidBinary)

  def __init__(self, *args, **kwargs):
    super(AaptBuilder, self).__init__(*args, **kwargs)

  def prepare(self, round_manager):
    round_manager.require_data('dex')

  def render_args(self, target, resource_dir, inputs):
    args = []

    # Glossary of used aapt flags. Aapt handles a ton of action, this will continue to expand.
    #   : 'package' is the main aapt operation (see class docstring for more info).
    #   : '-M' is the AndroidManifest.xml of the project.
    #   : '-S' points to the resource_dir to "spider" down while collecting resources.
    #   : '-I' packages to add to base "include" set, here the android.jar of the target-sdk.
    #   : '--ignored-assets' patterns for the aapt to skip. This is the default w/ 'BUILD*' added.
    #   : '-F' The name and location of the .apk file to output
    #   : additional positional arguments are treated as input directories to gather files from.
    args.extend([self.aapt_tool(target.build_tools_version)])
    args.extend(['package', '-M', target.manifest])
    args.extend(['-S'])
    args.extend(resource_dir)
    args.extend(['-I', self.android_jar_tool(target.target_sdk)])
    args.extend(['--ignore-assets', self.ignored_assets])
    args.extend(['-F', os.path.join(self.workdir, target.app_name + '-unsigned.apk')])
    args.extend(inputs)
    log.debug('Executing: {0}'.format(args))
    return args

  def execute(self):
    safe_mkdir(self.workdir)
    # TODO(mateor) map stderr and stdout to workunit streams (see CR 859)
    with self.context.new_workunit(name='apk-bundle', labels=[WorkUnit.MULTITOOL]):
      targets = self.context.targets(self.is_app)
      with self.invalidated(targets) as invalidation_check:
        invalid_targets = []
        for vt in invalidation_check.invalid_vts:
          invalid_targets.extend(vt.targets)
        for target in invalid_targets:
          # 'input_dirs' is the folder containing the Android dex file
          input_dirs = []
          # 'gen_out' holds resource folders (e.g. 'res')
          gen_out = []
          mapping = self.context.products.get('dex')
          for basedir in mapping.get(target):
            input_dirs.append(basedir)

          def gather_resources(target):
            """Gather the 'resource_dir' of the target"""
            if isinstance(target, AndroidResources):
              gen_out.append(os.path.join(get_buildroot(), target.resource_dir))

          target.walk(gather_resources)

          process = subprocess.Popen(self.render_args(target, gen_out, input_dirs))
          result = process.wait()
          if result != 0:
            raise TaskError('Android aapt tool exited non-zero ({code})'.format(code=result))
    for target in targets:
      self.context.products.get('apk').add(target, self.workdir).append(target.app_name + "-unsigned.apk")

