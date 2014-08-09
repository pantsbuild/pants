# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shlex

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.executor import CommandLineGrabber
from pants.java.util import execute_java
from pants.util.dirutil import safe_open


def is_binary(target):
  return isinstance(target, JvmBinary)


class JvmRun(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest = "run_jvmargs", action="append",
      help = "Run binary in a jvm with these extra jvm args.")

    option_group.add_option(mkflag("args"), dest = "run_args", action="append",
      help = "Run binary with these main() args.")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True), dest = "run_debug",
      action="callback", callback=mkflag.set_bool, default=False,
      help = "[%default] Run binary with a debugger")

    option_group.add_option(mkflag('only-write-cmd-line'), dest = 'only_write_cmd_line',
      action='store', default=None,
      help = '[%default] Instead of running, just write the cmd line to this file')

  def __init__(self, *args, **kwargs):
    super(JvmRun, self).__init__(*args, **kwargs)
    self.jvm_args = self.context.config.getlist('jvm-run', 'jvm_args', default=[])
    if self.context.options.run_jvmargs:
      for arg in self.context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.args = []
    if self.context.options.run_args:
      for arg in self.context.options.run_args:
        self.args.extend(shlex.split(arg))
    if self.context.options.run_debug:
      self.jvm_args.extend(self.context.config.getlist('jvm', 'debug_args'))
    self.confs = self.context.config.getlist('jvm-run', 'confs', default=['default'])
    self.only_write_cmd_line = self.context.options.only_write_cmd_line

  def prepare(self, round_manager):
    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # phase. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def execute(self):
    # The called binary may block for a while, allow concurrent pants activity during this pants
    # idle period.
    #
    # TODO(John Sirois): refactor lock so that I can do:
    # with self.context.lock.yield():
    #   - blocking code
    #
    # Currently re-acquiring the lock requires a path argument that was set up by the goal
    # execution engine.  I do not want task code to learn the lock location.
    # http://jira.local.twitter.com/browse/AWESOME-1317
    binary = self.require_single_root_target()

    # We can't throw if binary isn't a JvmBinary, because perhaps we were called on a
    # python_binary, in which case we have to no-op and let python_run do its thing.
    # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
    if isinstance(binary, JvmBinary):
      executor = CommandLineGrabber() if self.only_write_cmd_line else None
      self.context.lock.release()
      exclusives_classpath = self.get_base_classpath_for_target(binary)
      result = execute_java(
        classpath=(self.classpath(confs=self.confs, exclusives_classpath=exclusives_classpath)),
        main=binary.main,
        executor=executor,
        jvm_options=self.jvm_args,
        args=self.args,
        workunit_factory=self.context.new_workunit,
        workunit_name='run',
        workunit_labels=[WorkUnit.RUN]
      )

      if self.only_write_cmd_line:
        with safe_open(self.only_write_cmd_line, 'w') as outfile:
          outfile.write(' '.join(executor.cmd))
      elif result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (binary.main, result),
                        exit_code=result)
