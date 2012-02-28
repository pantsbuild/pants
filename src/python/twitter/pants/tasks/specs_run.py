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

__author__ = 'John Sirois'

import os
import re

from twitter.common.collections import OrderedSet

from twitter.pants import get_buildroot, is_scala, is_test
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.binary_utils import profile_classpath, runjava, safe_args

class SpecsRun(Task):
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

    classes = context.options.specs_run_tests
    self.tests = map(self.normalize, classes) if classes else None

  def execute(self, targets):
    if not self.skip:
      def run_tests(main, args):
        classpath = profile_classpath(self.profile)
        classpath.extend(os.path.join(get_buildroot(), path)
                         for path in ('src/resources', 'tests/resources'))
        with self.context.state('classpath', []) as cp:
          classpath.extend(jar for conf, jar in cp if conf in self.confs)

        result = runjava(jvmargs=self.java_args, classpath=classpath, main=main, args=args)
        if result != 0:
          raise TaskError()

      args = []
      if self.color:
        args.append('--color')

      if self.tests:
        args.append('--classes')
        args.append(','.join(self.tests))
        run_tests('run', args)
      else:
        with safe_args(self.calculate_tests(targets)) as tests:
          if tests:
            args.append('--specs-files=%s' % ','.join(tests))
            run_tests('com.twitter.common.testing.ExplicitSpecsRunnerMain', args)

  def calculate_tests(self, targets):
    tests = OrderedSet()
    for target in targets:
      if is_scala(target) and is_test(target):
        tests.update(os.path.join(target.target_base, test) for test in target.sources)
    return tests

  def normalize(self, classname_or_file):
    if not classname_or_file.endswith('.scala'):
      return classname_or_file

    basedir = calculate_basedir(classname_or_file)
    return os.path.relpath(classname_or_file, basedir).replace('/', '.').replace('.scala', '')


PACKAGE_PARSER = re.compile(r'^\s*package\s+([\w.]+)\s*')

def calculate_basedir(file):
  with open(file, 'r') as source:
    for line in source:
      match = PACKAGE_PARSER.match(line)
      if match:
        package = match.group(1)
        packagedir = package.replace('.', '/')
        dir = os.path.dirname(file)
        if not dir.endswith(packagedir):
          raise TaskError('File %s declares a mismatching package %s' % (file, package))
        return dir[:-len(packagedir)]

  raise TaskError('Could not calculate a base dir for: %s' % file)
