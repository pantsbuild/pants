# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.java.util import execute_java
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.target import Target
from pants.console.stty_utils import preserve_stty_settings


class ScalaRepl(JvmTask, JvmToolTaskMixin):
  def __init__(self, *args, **kwargs):
    super(ScalaRepl, self).__init__(*args, **kwargs)

    self._bootstrap_key = 'scala-repl'
    self.register_jvm_tool_from_config(self._bootstrap_key, self.context.config,
                                       ini_section='scala-repl',
                                       ini_key='bootstrap-tools',
                                       default=['//:scala-repl-2.9.3'])

    self.main = self.context.config.get('scala-repl', 'main')

  def prepare(self, round_manager):
    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def execute(self):
    (accept_predicate, reject_predicate) = Target.lang_discriminator('java')
    targets = self.require_homogeneous_targets(accept_predicate, reject_predicate)
    if targets:
      tools_classpath = self.tool_classpath(self._bootstrap_key)
      self.context.release_lock()
      with preserve_stty_settings():
        exclusives_classpath = self.get_base_classpath_for_target(targets[0])
        classpath = self.classpath(tools_classpath,
                                   confs=self.confs,
                                   exclusives_classpath=exclusives_classpath)

        print('')  # Start REPL output on a new line.
        try:
          # NOTE: We execute with no workunit, as capturing REPL output makes it very sluggish.
          execute_java(classpath=classpath,
                       main=self.main,
                       jvm_options=self.jvm_options,
                       args=self.args)
        except KeyboardInterrupt:
          # TODO(John Sirois): Confirm with Steve Gury that finally does not work on mac and an
          # explicit catch of KeyboardInterrupt is required.
          pass
