# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_task import PythonTask
from pants.backend.python.test_builder import PythonTestBuilder
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.contextutil import environment_as
from pants.util.strutil import safe_shlex_split


class PytestRun(PythonTask):
  @classmethod
  def register_options(cls, register):
    super(PytestRun, cls).register_options(register)
    register('--fast', action='store_true', default=True,
             help='Run all tests in a single chroot. If turned off, each test target will '
                  'create a new chroot, which will be much slower.')
    register('--options', action='append', help='Pass these options to pytest.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    def is_python_test(target):
      # Note that we ignore PythonTestSuite, because we'll see the PythonTests targets
      # it depends on anyway,so if we don't we'll end up running the tests twice.
      # TODO(benjy): Once we're off the 'build' command we can get rid of python_test_suite,
      # or make it an alias of dependencies().
      return isinstance(target, PythonTests)

    test_targets = list(filter(is_python_test, self.context.targets()))
    if test_targets:
      self.context.release_lock()

      debug = self.get_options().level == 'debug'

      args = ['--color', 'yes'] if self.get_options().colors else []
      for options in self.get_options().options + self.get_passthru_args():
        args.extend(safe_shlex_split(options))
      test_builder = PythonTestBuilder(context=self.context,
                                       targets=test_targets,
                                       args=args,
                                       interpreter=self.interpreter,
                                       fast=self.get_options().fast,
                                       debug=debug)
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
