# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.binary_util import safe_args
from pants.java.util import execute_java


class SpecsRun(JvmTask, JvmToolTaskMixin):
  @classmethod
  def register_options(cls, register):
    super(SpecsRun, cls).register_options(register)
    register('--skip', action='store_true', help='Skip running specs.')
    register('--test', action='append',
             help='Force running of just these specs.  Tests can be specified either by fully '
                  'qualified classname or full file path.')
    cls.register_jvm_tool(register, 'specs', default=['//:scala-specs'])

  @classmethod
  def prepare(cls, options, round_manager):
    super(SpecsRun, cls).prepare(options, round_manager)

    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(SpecsRun, self).__init__(*args, **kwargs)
    self.skip = self.get_options().skip
    self.tests = self.get_options().test

  def execute(self):
    if not self.skip:
      targets = self.context.targets()

      def run_tests(tests):
        args = ['--color'] if self.get_options().colors else []
        args.append('--specs=%s' % ','.join(tests))
        specs_runner_main = 'com.twitter.common.testing.ExplicitSpecsRunnerMain'

        bootstrapped_cp = self.tool_classpath('specs')
        classpath = self.classpath(targets, cp=bootstrapped_cp)

        result = execute_java(
          classpath=classpath,
          main=specs_runner_main,
          jvm_options=self.jvm_options,
          args=self.args + args,
          workunit_factory=self.context.new_workunit,
          workunit_name='specs',
          workunit_labels=[WorkUnit.TEST]
        )
        if result != 0:
          raise TaskError('java %s ... exited non-zero (%i)' % (specs_runner_main, result))

      if self.tests:
        run_tests(self.tests)
      else:
        with safe_args(self.calculate_tests(targets), self.get_options()) as tests:
          if tests:
            run_tests(tests)

  def calculate_tests(self, targets):
    tests = OrderedSet()
    for target in targets:
      if target.is_scala and target.is_test:
        tests.update(target.sources_relative_to_buildroot())
    return tests
