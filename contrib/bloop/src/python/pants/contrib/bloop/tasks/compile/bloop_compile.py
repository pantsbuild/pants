# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

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
      'bloop-launcher',
      classpath=[
        JarDependency(
          org='ch.epfl.scala',
          name='bloop-launcher_2.12',
          rev='1.2.5',
        ),
      ],
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopCompile, cls).prepare(options, round_manager)
    round_manager.require_data('bloop_output_dir')

  def execute(self):
    # TODO: no-op for now until it works!
    return

    bloop_output_dir = self.context.products.get_data('bloop_output_dir')

    bsp_launcher_process = self.runjava(
      classpath=self.tool_classpath('bloop-launcher'),
      main='bloop.launcher.Launcher',
      jvm_options=[],
      # NB: jvm options need to be prefixed with -J (TODO: does this work for jvm properties?)!!!
      args=[
        '-J{}'.format(opt) for opt in self.get_options().jvm_options
      ] + [
        # TODO: how does the launcher resolve the directory to find bloop logs in? It seems like it
        # resolves it from `user.home`/.bloop?? We might be able to hack that in for now.
        '-J-Duser.home={}'.format(os.dirname(bloop_output_dir)),
      ],
      workunit_name='bloop-compile',
      workunit_labels=[WorkUnitLabel.COMPILER],
      do_async=True,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE)

    # TODO: speak bsp to it and tell it where to locate everything / etc!
