# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shlex
import subprocess

from pants.java.util import execute_java
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.jvm_task import JvmTask


class ScalaRepl(JvmTask, JvmToolTaskMixin):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest="run_jvmargs", action="append",
                            help="Run the repl in a jvm with these extra jvm args.")
    option_group.add_option(mkflag('args'), dest='run_args', action='append',
                            help='run the repl in a jvm with extra args.')

  def __init__(self, context, workdir):
    super(ScalaRepl, self).__init__(context, workdir)
    self.jvm_args = context.config.getlist('scala-repl', 'jvm_args', default=[])
    if context.options.run_jvmargs:
      for arg in context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.confs = context.config.getlist('scala-repl', 'confs', default=['default'])
    self._bootstrap_key = 'scala-repl'
    bootstrap_tools = context.config.getlist('scala-repl', 'bootstrap-tools')
    self.register_jvm_tool(self._bootstrap_key, bootstrap_tools)
    self.main = context.config.get('scala-repl', 'main')
    self.args = context.config.getlist('scala-repl', 'args', default=[])
    if context.options.run_args:
      for arg in context.options.run_args:
        self.args.extend(shlex.split(arg))

  def execute(self):
    # The repl session may last a while, allow concurrent pants activity during this pants idle
    # period.
    tools_classpath = self.tool_classpath(self._bootstrap_key)

    self.context.lock.release()
    self.save_stty_options()

    targets = self.context.targets()
    classpath = self.classpath(tools_classpath,
                               confs=self.confs,
                               exclusives_classpath=self.get_base_classpath_for_target(targets[0]))

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
    self.restore_ssty_options()

  def save_stty_options(self):
    """
    The scala REPL changes some stty parameters and doesn't save/restore them after
    execution, so if you have a terminal with non-default stty options, you end
    up to a broken terminal (need to do a 'reset').
    """
    self.stty_options = self.run_cmd('stty -g 2>/dev/null')

  def restore_ssty_options(self):
    self.run_cmd('stty ' + self.stty_options)

  def run_cmd(self, cmd):
    po = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    stdout, _ = po.communicate()
    return stdout
