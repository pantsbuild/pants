# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.target import Target
from pants.console.stty_utils import preserve_stty_settings
from pants.java.util import execute_java


class ScalaRepl(JvmTask, JvmToolMixin):
  @classmethod
  def register_options(cls, register):
    super(ScalaRepl, cls).register_options(register)
    register('--main', default='scala.tools.nsc.MainGenericRunner',
             help='The entry point for running the repl.')
    cls.register_jvm_tool(register, 'scala-repl', default=['//:scala-repl'])

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaRepl, cls).prepare(options, round_manager)

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
      tools_classpath = self.tool_classpath('scala-repl')
      self.context.release_lock()
      with preserve_stty_settings():
        classpath = self.classpath(targets, cp=tools_classpath)

        print('')  # Start REPL output on a new line.
        try:
          # NOTE: We execute with no workunit, as capturing REPL output makes it very sluggish.
          execute_java(classpath=classpath,
                       main=self.get_options().main,
                       jvm_options=self.jvm_options,
                       args=self.args)
        except KeyboardInterrupt:
          # TODO(John Sirois): Confirm with Steve Gury that finally does not work on mac and an
          # explicit catch of KeyboardInterrupt is required.
          pass
