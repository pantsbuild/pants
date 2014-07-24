# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shlex

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.backend.python.test_builder import PythonTestBuilder
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_task import PythonTask
from pants.util.contextutil import environment_as


class PytestRun(PythonTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(PytestRun, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag('fast'), mkflag('fast', negate=True),
                            dest='pytest_run_fast',
                            action='callback', callback=mkflag.set_bool, default=True,
                            help='[%default] Run all tests in a single chroot. If set to false, '
                                 'each test target will create a new chroot, which will be much '
                                 'slower.')
    # TODO(benjy): Support direct passthru of pytest flags.
    option_group.add_option(mkflag('options'),
                            dest='pytest_run_options',
                            action='append', default=[],
                            help='[%default] options to pass to the underlying pytest runner.')

  def execute(self):
    def is_python_test(target):
      # Note that we ignore PythonTestSuite, because we'll see the PythonTests targets
      # it depends on anyway,so if we don't we'll end up running the tests twice.
      # TODO(benjy): Once we're off the 'build' command we can get rid of python_test_suite,
      # or make it an alias of dependencies().
      return isinstance(target, PythonTests)

    test_targets = list(filter(is_python_test, self.context.targets()))
    if test_targets:
      self.context.lock.release()

      # TODO(benjy): Only color on terminals that support it.
      args = ['--color', 'yes']
      # TODO(benjy): A less hacky way to find the log level.
      if self.context.options.log_level == 'debug':
        args.append('-s')  # Make pytest emit all stdout/stderr, even for successful tests.
      if self.context.options.pytest_run_options:
        for options in self.context.options.pytest_run_options:
          args.extend(shlex.split(options))
      test_builder = PythonTestBuilder(targets=test_targets,
                                       args=args,
                                       interpreter=self.interpreter,
                                       conn_timeout=self.conn_timeout,
                                       fast=self.context.options.pytest_run_fast)
      with self.context.new_workunit(name='run',
                                     labels=[WorkUnit.TOOL, WorkUnit.TEST]) as workunit:
        # pytest uses py.io.terminalwriter for output. That class detects the terminal
        # width and attempts to use all of it. However we capture and indent the console
        # output, leading to weird-looking line wraps. So we trick the detection code
        # into thinking the terminal window is narrower than it is.
        cols = os.environ.get('COLUMNS', 80)
        with environment_as(COLUMNS=str(int(cols) - 30)):
          stdout = workunit.output('stdout') if workunit else None
          stderr = workunit.output('stderr') if workunit else None
          if test_builder.run(stdout=stdout, stderr=stderr):
            raise TaskError()
