# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import time

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.util.process_handler import subprocess


class BloopCompile(NailgunTask):

  @classmethod
  def register_options(cls, register):
    super(BloopCompile, cls).register_options(register)

    cls.register_jvm_tool(
      register,
      'bloop-compile-wrapper',
      classpath=[
        JarDependency(
          org='org.pantsbuild',
          name='bloop-compile-wrapper_2.12',
          rev='???',
        ),
      ],
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopCompile, cls).prepare(options, round_manager)
    round_manager.require_data('bloop_output_dir')

  _supported_languages = ['java', 'scala']

  def execute(self):
    bsp_launcher_process = self.runjava(
      classpath=self.tool_classpath('bloop-compile-wrapper'),
      main='pants.contrib.bloop.compile.PantsCompileMain',
      jvm_options=[],
      # TODO: jvm options need to be prefixed with -J if we want to use them!
      args=[
        t.id for t in self.context.target_roots
      ],
      workunit_name='bloop-compile',
      workunit_labels=[WorkUnitLabel.COMPILER],
      do_async=True,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE)

    time.sleep(2)
    msg = ''
    while not msg:
      msg = bsp_launcher_process.stdout.readline()
    self.context.log.info('msg: {}'.format(msg))

    bsp_launcher_process.terminate()
