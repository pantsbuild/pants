# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shlex

from pants.java.util import execute_java
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.target import Target
from pants.console.stty_utils import preserve_stty_settings


class ScalaRepl(JvmTask, JvmToolTaskMixin):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest="run_jvmargs", action="append",
                            help="Run the repl in a jvm with these extra jvm args.")
    option_group.add_option(mkflag('args'), dest='run_args', action='append',
                            help='run the repl in a jvm with extra args.')

  def __init__(self, *args, **kwargs):
    super(ScalaRepl, self).__init__(*args, **kwargs)
    self.jvm_args = self.context.config.getlist('scala-repl', 'jvm_args', default=[])
    if self.context.options.run_jvmargs:
      for arg in self.context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.confs = self.context.config.getlist('scala-repl', 'confs', default=['default'])
    self._bootstrap_key = 'scala-repl'
    bootstrap_tools = self.context.config.getlist('scala-repl', 'bootstrap-tools')
    self.register_jvm_tool(self._bootstrap_key, bootstrap_tools)
    self.main = self.context.config.get('scala-repl', 'main')
    self.args = self.context.config.getlist('scala-repl', 'args', default=[])
    if self.context.options.run_args:
      for arg in self.context.options.run_args:
        self.args.extend(shlex.split(arg))

  def prepare(self, round_manager):
    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # phase. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def execute(self):
    (accept_predicate, reject_predicate) = Target.lang_discriminator('java')
    targets = self.require_homogeneous_targets(accept_predicate, reject_predicate)
    if targets:
      tools_classpath = self.tool_classpath(self._bootstrap_key)
      self.context.lock.release()
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
                       jvm_options=self.jvm_args,
                       args=self.args)
        except KeyboardInterrupt:
          # TODO(John Sirois): Confirm with Steve Gury that finally does not work on mac and an
          # explicit catch of KeyboardInterrupt is required.
          pass
