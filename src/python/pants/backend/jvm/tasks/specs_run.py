# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.jvm_task import JvmTask
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
    # TODO: Get rid of this in favor of the inherited global color flag.
    register('--color', action='store_true', default=True,
             help='Emit test result with ANSI terminal color codes.')

  def __init__(self, *args, **kwargs):
    super(SpecsRun, self).__init__(*args, **kwargs)

    self._specs_bootstrap_key = 'specs'
    self.register_jvm_tool_from_config(self._specs_bootstrap_key, self.context.config,
                                       ini_section='specs-run',
                                       ini_key='bootstrap-tools',
                                       default=['//:scala-specs-2.9.3'])

    self.skip = self.get_options().skip
    self.color = self.get_options().color
    self.tests = self.get_options().test

  def prepare(self, round_manager):
    super(SpecsRun, self).prepare(round_manager)

    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def execute(self):
    if not self.skip:
      targets = self.context.targets()

      def run_tests(tests):
        args = ['--color'] if self.color else []
        args.append('--specs=%s' % ','.join(tests))
        specs_runner_main = 'com.twitter.common.testing.ExplicitSpecsRunnerMain'

        bootstrapped_cp = self.tool_classpath(self._specs_bootstrap_key)
        classpath = self.classpath(
            bootstrapped_cp,
            confs=self.confs,
            exclusives_classpath=self.get_base_classpath_for_target(targets[0]))

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
        with safe_args(self.calculate_tests(targets)) as tests:
          if tests:
            run_tests(tests)

  def calculate_tests(self, targets):
    tests = OrderedSet()
    for target in targets:
      if target.is_scala and target.is_test:
        tests.update(target.sources_relative_to_buildroot())
    return tests
