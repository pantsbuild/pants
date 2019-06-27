# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json

from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.util.collections import assert_single_element
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
    jvm_targets = self.get_targets(lambda t: isinstance(t, JvmTarget))

    runjava_args = dict(
      classpath=self.tool_classpath('bloop-compile-wrapper'),
      main='pants.contrib.bloop.compile.PantsCompileMain',
      jvm_options=[],
      # TODO: jvm options need to be prefixed with -J and passed to the LauncherMain if we want to
      # use them!
      args=[
        'debug',
        # self.get_options().level,
        '--',
      ] + [
        t.id for t in jvm_targets
      ],
      workunit_name='bloop-compile',
      workunit_labels=[WorkUnitLabel.COMPILER])

    with self.context.new_workunit('bloop-workunit-wrapper') as wu:
      use_async = True
      if use_async:
        runjava_args.update(dict(
          do_async=True,
          stdin=subprocess.PIPE,
          stdout=subprocess.PIPE))
        bsp_launcher_process = self.runjava(**runjava_args)
        stdout, stderr = bsp_launcher_process.communicate(stdin=b'')
        assert stderr is None
        target_name_to_classes_dir = json.loads(stdout.decode('utf-8'))
        rc = bsp_launcher_process.wait()
      else:
        use_direct_subprocess_hack = False
        if use_direct_subprocess_hack:
          raise Exception('wow')
        else:
          rc = self.runjava(**runjava_args)
          runjava_workunit = assert_single_element(
            w for w in wu.children
            if w.name == 'bloop-compile')
          target_name_to_classes_dir = json.loads(
            runjava_workunit.output('stdout').read_from(0).decode('utf-8'))

      if rc != 0:
        raise TaskError('???', exit_code=rc)

    self.context.log.info('target_name_to_classes_dir: {}'.format(target_name_to_classes_dir))

    for target in jvm_targets:
      classes_dir = self.context.products.get_data('bloop_classes_dir').get(target, None)
      if classes_dir:
        bloop_internal_classes_dir = target_name_to_classes_dir.get(target.id, None)
        if bloop_internal_classes_dir is not None:
          new_cp_entry = ClasspathEntry(bloop_internal_classes_dir)
          self.context.products.get_data('runtime_classpath').add_for_target(
            target,
            [(conf, new_cp_entry) for conf in self._confs])

    self.context.log.info('finished compile!')
