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

import os

from twitter.common.collections import OrderedSet

from twitter.pants import is_scala, is_test
from twitter.pants.binary_util import profile_classpath, runjava_indivisible, safe_args
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.jvm_task import JvmTask

class SpecsRun(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True), dest = "specs_run_skip",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Skip running specs")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True), dest = "specs_run_debug",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Run specs with a debugger")

    option_group.add_option(mkflag("jvmargs"), dest = "specs_run_jvmargs", action="append",
                            help = "Runs specs in a jvm with these extra jvm args.")

    option_group.add_option(mkflag("test"), dest = "specs_run_tests", action="append",
                            help = "[%default] Force running of just these specs.  Tests can be "
                                   "specified either by classname or filename.")

    option_group.add_option(mkflag("color"), mkflag("color", negate=True),
                            dest="specs_run_color", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Emit test result with ANSI terminal color codes.")

  def __init__(self, context):
    Task.__init__(self, context)

    self.profile = context.config.get('specs-run', 'profile')
    self.confs = context.config.getlist('specs-run', 'confs')

    self.java_args = context.config.getlist('specs-run', 'args', default=[])
    if context.options.specs_run_jvmargs:
      self.java_args.extend(context.options.specs_run_jvmargs)
    if context.options.specs_run_debug:
      self.java_args.extend(context.config.getlist('jvm', 'debug_args'))

    self.skip = context.options.specs_run_skip
    self.color = context.options.specs_run_color

    self.workdir = context.config.get('specs-run', 'workdir')

    self.tests = context.options.specs_run_tests

  def execute(self, targets):
    if not self.skip:
      def run_tests(tests):
        opts = ['--color'] if self.color else []
        opts.append('--specs=%s' % ','.join(tests))

        result = runjava_indivisible(
          jvmargs=self.java_args,
          classpath=self.classpath(profile_classpath(self.profile), confs=self.confs),
          main='com.twitter.common.testing.ExplicitSpecsRunnerMain',
          opts=opts
        )
        if result != 0:
          raise TaskError()

      if self.tests:
        run_tests(self.tests)
      else:
        with safe_args(self.calculate_tests(targets)) as tests:
          if tests:
            run_tests(tests)

  def calculate_tests(self, targets):
    tests = OrderedSet()
    for target in targets:
      if is_scala(target) and is_test(target):
        tests.update(os.path.join(target.target_base, test) for test in target.sources)
    return tests
