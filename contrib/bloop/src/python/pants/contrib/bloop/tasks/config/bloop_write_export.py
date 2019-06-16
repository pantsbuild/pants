# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir
from pants.util.process_handler import subprocess

from pants.contrib.bloop.tasks.config.bloop_export_config import BloopExportConfig


class BloopWriteExport(NailgunTask):

  @classmethod
  def register_options(cls, register):
    super(BloopWriteExport, cls).register_options(register)

    register('--output-dir', type=str, default='.bloop', advanced=True,
             help='Relative path to the buildroot to write the ensime config to.')

    cls.register_jvm_tool(
      register,
      'bloop-config-gen',
      classpath=[
        JarDependency(
          org='org.pantsbuild',
          name='bloop-config-gen_2.12',
          rev='???',
        ),
      ],
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopWriteExport, cls).prepare(options, round_manager)
    round_manager.require_data(BloopExportConfig.BloopExport)

  @classmethod
  def product_types(cls):
    return ['bloop_output_dir']

  def execute(self):
    bloop_export = self.context.products.get_data(BloopExportConfig.BloopExport)

    export_result = json.dumps(bloop_export.exported_targets_map, indent=4, separators=(',', ': '))

    output_dir = os.path.join(get_buildroot(), self.get_options().output_dir)
    safe_mkdir(output_dir)

    argv = [
      get_buildroot(),
      bloop_export.reported_scala_version,
      self.get_options().pants_distdir,
      output_dir,
    ]

    env = {
      'SCALA_COMPILER_JARS_CLASSPATH': ':'.join(bloop_export.scala_compiler_jars),
      'PANTS_TARGET_TYPES': ':'.join(bloop_export.pants_target_types),
    }

    # self.context.log.debug('export_result:\n{}'.format(export_result))
    self.context.log.debug('env:\n{}'.format(env))


    with environment_as(**env):
      proc = self.runjava(
        classpath=self.tool_classpath('bloop-config-gen'),
        main='pants.contrib.bloop.config.BloopConfigGen',
        jvm_options=self.get_options().jvm_options,
        args=argv,
        do_async=True,
        workunit_name='bloop-config-gen',
        workunit_labels=[WorkUnitLabel.TOOL],
        stdin=subprocess.PIPE)
      # Write the json export to the subprocess stdin.
      stdout, stderr = proc.communicate(stdin=export_result.encode())
      assert stdout is None
      assert stderr is None
      rc = proc.wait()
      if rc != 0:
        raise TaskError('???', exit_code=rc)

    self.context.products.register_data('bloop_output_dir', output_dir)
