# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
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
    round_manager.require_data('bloop_classes_dir')

  _supported_languages = ['java', 'scala']

  _confs = Zinc.DEFAULT_CONFS

  def execute(self):
    runjava_args = dict(
      classpath=self.tool_classpath('bloop-compile-wrapper'),
      main='pants.contrib.bloop.compile.PantsCompileMain',
      jvm_options=[],
      # TODO: jvm options need to be prefixed with -J and passed to the LaumcherMain if we want to
      # use them!
      args=[
        'debug',
        # self.get_options().level,
        '--',
      ] + [
        t.id for t in self.context.target_roots
      ],
      workunit_name='bloop-compile',
      workunit_labels=[WorkUnitLabel.COMPILER])

    use_async = False
    if use_async:
      runjava_args.update(dict(
        do_async=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE))
      bsp_launcher_process = self.runjava(**runjava_args)
      msg = ''
      while not msg:
        msg = bsp_launcher_process.stdout.readline()
      # assert msg == 'compile complete!'
      self.context.log.info('msg: {}'.format(msg))
      bsp_launcher_process.stdin.close()
      bsp_launcher_process.stdout.close()
      bsp_launcher_process.kill()
    else:
      rc = self.runjava(**runjava_args)
      if rc != 0:
        raise TaskError(exit_code=rc)

    for target in self.context.targets():
      classes_dir = self.context.products.get_data('bloop_classes_dir').get(target, None)
      if classes_dir is not None:
        self.context.products.get_data('runtime_classpath').add_for_target(
          target,
          [(conf, classes_dir) for conf in self._confs])

    self.context.log.info('finished compile!')
