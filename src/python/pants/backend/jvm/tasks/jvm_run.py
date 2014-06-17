# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shlex

from twitter.common.dirutil import safe_open

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.executor import CommandLineGrabber
from pants.java.util import execute_java


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

  def __init__(self, context, workdir):
    super(JvmRun, self).__init__(context, workdir)
    self.jvm_args = context.config.getlist('jvm-run', 'jvm_args', default=[])
    if context.options.run_jvmargs:
      for arg in context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.args = []
    if context.options.run_args:
      for arg in context.options.run_args:
        self.args.extend(shlex.split(arg))
    if context.options.run_debug:
      self.jvm_args.extend(context.config.getlist('jvm', 'debug_args'))
    self.confs = context.config.getlist('jvm-run', 'confs', default=['default'])
    self.only_write_cmd_line = context.options.only_write_cmd_line
    context.products.require_data('exclusives_groups')

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

    target_roots = self.context.target_roots
    if len(target_roots) == 0:
      raise TaskError('No target specified.')
    elif len(target_roots) > 1:
      raise TaskError('Multiple targets specified: %s' % ', '.join([repr(t) for t in target_roots]))
    binary = target_roots[0]

    if isinstance(binary, JvmBinary):
      # We can't throw if binary isn't a JvmBinary, because perhaps we were called on a
      # python_binary, in which case we have to no-op and let python_run do its thing.
      # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
      egroups = self.context.products.get_data('exclusives_groups')
      group_key = egroups.get_group_key_for_target(binary)
      group_classpath = egroups.get_classpath_for_group(group_key)

      executor = CommandLineGrabber() if self.only_write_cmd_line else None
      self.context.lock.release()
      result = execute_java(
        classpath=(self.classpath(confs=self.confs, exclusives_classpath=group_classpath)),
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
