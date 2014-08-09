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
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('skip'), mkflag('skip', negate=True), dest='specs_run_skip',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Skip running specs')

    option_group.add_option(mkflag('debug'), mkflag('debug', negate=True), dest='specs_run_debug',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Run specs with a debugger')

    option_group.add_option(mkflag('jvmargs'), dest='specs_run_jvm_options', action='append',
                            help='Runs specs in a jvm with these extra jvm options.')

    option_group.add_option(mkflag('test'), dest='specs_run_tests', action='append',
                            help='[%default] Force running of just these specs.  Tests can be '
                                 'specified either by fully qualified classname or '
                                 'full file path.')

    option_group.add_option(mkflag('color'), mkflag('color', negate=True),
                            dest='specs_run_color', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Emit test result with ANSI terminal color codes.')

  def __init__(self, *args, **kwargs):
    super(SpecsRun, self).__init__(*args, **kwargs)

    self._specs_bootstrap_key = 'specs'
    bootstrap_tools = self.context.config.getlist('specs-run', 'bootstrap-tools',
                                                  default=[':scala-specs-2.9.3'])
    self.register_jvm_tool(self._specs_bootstrap_key, bootstrap_tools)

    self.confs = self.context.config.getlist('specs-run', 'confs', default=['default'])

    self._jvm_options = self.context.config.getlist('specs-run', 'jvm_args', default=[])
    if self.context.options.specs_run_jvm_options:
      self._jvm_options.extend(self.context.options.specs_run_jvm_options)
    if self.context.options.specs_run_debug:
      self._jvm_options.extend(self.context.config.getlist('jvm', 'debug_args'))

    self.skip = self.context.options.specs_run_skip
    self.color = self.context.options.specs_run_color

    self.tests = self.context.options.specs_run_tests

  def prepare(self, round_manager):
    super(SpecsRun, self).prepare(round_manager)

    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # phase. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
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
          jvm_options=self._jvm_options,
          args=args,
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
