# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.fs.fs import expand_path
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import CommandLineGrabber
from pants.util.dirutil import safe_open


_CWD_NOT_PRESENT = 'CWD NOT PRESENT'
logger = logging.getLogger(__name__)


def is_binary(target):
  return isinstance(target, JvmBinary)


class JvmRun(JvmTask):

  @classmethod
  def register_options(cls, register):
    super(JvmRun, cls).register_options(register)
    register('--only-write-cmd-line', metavar='<file>',
             help='Instead of running, just write the cmd line to this file.')
    # Note the unusual registration pattern. This is so we can support three cases:
    # --cwd=<path>
    # --cwd (defaults to the value of 'const', which is None here)
    # No explicit --cwd at all (defaults to the value of 'default')
    register('--cwd', default=_CWD_NOT_PRESENT, nargs='?',
             help='Set the working directory. If no argument is passed, use the target path.')
    register('--main', metavar='<main class>',
             help='Invoke this class (overrides "main"" attribute in jvm_binary targets)')

  @classmethod
  def subsystem_dependencies(cls):
    return super(JvmRun, cls).subsystem_dependencies() + (DistributionLocator,)

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmRun, cls).prepare(options, round_manager)

    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(JvmRun, self).__init__(*args, **kwargs)
    self.only_write_cmd_line = self.get_options().only_write_cmd_line
    self.args.extend(self.get_passthru_args())

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
    target = self.require_single_root_target()

    working_dir = None
    cwd_opt = self.get_options().cwd
    if cwd_opt != _CWD_NOT_PRESENT:
      working_dir = self.get_options().cwd
      if not working_dir:
        working_dir = target.address.spec_path
    logger.debug("Working dir is {0}".format(working_dir))

    if isinstance(target, JvmApp):
      binary = target.binary
    else:
      binary = target

    # We can't throw if binary isn't a JvmBinary, because perhaps we were called on a
    # python_binary, in which case we have to no-op and let python_run do its thing.
    # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
    if isinstance(binary, JvmBinary):
      jvm = DistributionLocator.cached()
      executor = CommandLineGrabber(jvm) if self.only_write_cmd_line else None
      self.context.release_lock()
      result = jvm.execute_java(
        classpath=(self.classpath([target])),
        main=self.get_options().main or binary.main,
        executor=executor,
        jvm_options=self.jvm_options,
        args=self.args,
        workunit_factory=self.context.new_workunit,
        workunit_name='run',
        workunit_labels=[WorkUnitLabel.RUN],
        cwd=working_dir,
      )

      if self.only_write_cmd_line:
        with safe_open(expand_path(self.only_write_cmd_line), 'w') as outfile:
          outfile.write(' '.join(executor.cmd))
      elif result != 0:
        raise TaskError('java {} ... exited non-zero ({})'.format(binary.main, result),
                        exit_code=result)
