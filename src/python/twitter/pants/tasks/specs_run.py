# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from twitter.common.collections import OrderedSet

from twitter.pants.base.workunit import WorkUnit
from twitter.pants.binary_util import safe_args
from twitter.pants.java.util import execute_java
from .jvm_task import JvmTask

from . import TaskError


class SpecsRun(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('skip'), mkflag('skip', negate=True), dest = 'specs_run_skip',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Skip running specs')

    option_group.add_option(mkflag('debug'), mkflag('debug', negate=True), dest = 'specs_run_debug',
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

  def __init__(self, context):
    super(SpecsRun, self).__init__(context)

    self._specs_bootstrap_key = 'specs'
    bootstrap_tools = context.config.getlist('specs-run', 'bootstrap-tools',
                                             default=[':scala-specs-2.9.3'])
    self._jvm_tool_bootstrapper.register_jvm_tool(self._specs_bootstrap_key, bootstrap_tools)

    self.confs = context.config.getlist('specs-run', 'confs')

    self._jvm_options = context.config.getlist('specs-run', 'jvm_args', default=[])
    if context.options.specs_run_jvm_options:
      self._jvm_options.extend(context.options.specs_run_jvm_options)
    if context.options.specs_run_debug:
      self._jvm_options.extend(context.config.getlist('jvm', 'debug_args'))

    self.skip = context.options.specs_run_skip
    self.color = context.options.specs_run_color

    self.workdir = context.config.get('specs-run', 'workdir')

    self.tests = context.options.specs_run_tests

  def execute(self, targets):
    if not self.skip:
      def run_tests(tests):
        args = ['--color'] if self.color else []
        args.append('--specs=%s' % ','.join(tests))
        specs_runner_main = 'com.twitter.common.testing.ExplicitSpecsRunnerMain'

        bootstrapped_cp = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(
            self._specs_bootstrap_key)
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
