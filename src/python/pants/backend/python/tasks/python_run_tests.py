# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.contextutil import environment_as

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.backend.python.test_builder import PythonTestBuilder
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_task import PythonTask


class PythonRunTests(PythonTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(PythonRunTests, cls).setup_parser(option_group, args, mkflag)
    # TODO(benjy): Support pass-thru of pytest flags.
    option_group.add_option(mkflag('fast'), mkflag('fast', negate=True),
                            dest='python_run_tests_fast',
                            action='callback', callback=mkflag.set_bool, default=True,
                            help='[%default] Run all tests in a single chroot. If set to false, '
                                 'each test target will create a new chroot, which will be much '
                                 'slower.')

  def execute(self):
    def is_python_test(target):
      # Note that we ignore PythonTestSuite, because we'll see the PythonTests targets
      # it depends on anyway,so if we don't we'll end up running the tests twice.
      # TODO(benjy): Once we're off the 'build' command we can get rid of python_test_suite,
      # or make it an alias of dependencies().
      return isinstance(target, PythonTests)

    test_targets = list(filter(is_python_test, self.context.targets()))
    if test_targets:
      # TODO(benjy): Only color on terminals that support it.
      test_builder = PythonTestBuilder(test_targets, ['--color', 'yes'],
                                       interpreter=self.interpreter,
                                       conn_timeout=self.conn_timeout,
                                       fast=self.context.options.python_run_tests_fast)
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