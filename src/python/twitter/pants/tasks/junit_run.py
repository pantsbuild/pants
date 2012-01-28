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

from twitter.pants import get_buildroot, is_java, is_test
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.binary_utils import profile_classpath, runjava

class JUnitRun(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True), dest = "junit_run_skip",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Skip running tests")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True), dest = "junit_run_debug",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Run junit tests with a debugger")

    option_group.add_option(mkflag("jvmargs"), dest = "junit_run_jvmargs", action="append",
                            help = "Runs junit tests in a jvm with these extra jvm args.")

    option_group.add_option(mkflag("test"), dest = "junit_run_tests", action="append",
                            help = "[%default] Force running of just these tests.  Tests can be "
                                   "specified using any of: [classname], [classname]#[methodname], "
                                   "[filename] or [filename]#[methodname]")

    outdir = mkflag("outdir")
    option_group.add_option(outdir, dest="junit_run_outdir",
                            help="Emit output in to this directory.")

    xmlreport = mkflag("xmlreport")
    option_group.add_option(xmlreport, mkflag("xmlreport", negate=True),
                            dest = "junit_run_xmlreport",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Causes an xml report to be output for each test "
                                   "class that is run.")

    option_group.add_option(mkflag("suppress-output"), mkflag("suppress-output", negate=True),
                            dest = "junit_run_suppress_output",
                            action="callback", callback=mkflag.set_bool, default=True,
                            help = "[%%default] Redirects test output to files in %s.  "
                                   "Implied by %s" % (outdir, xmlreport))

  def __init__(self, context):
    Task.__init__(self, context)

    self.confs = context.config.getlist('junit-run', 'confs')
    self.profile = context.config.get('junit-run', 'profile')

    self.java_args = context.config.getlist('junit-run', 'args', default=[])
    if context.options.junit_run_jvmargs:
      self.java_args.extend(context.options.junit_run_jvmargs)
    if context.options.junit_run_debug:
      self.java_args.extend(context.config.getlist('jvm', 'debug_args'))

    classes = context.options.junit_run_tests
    self.tests = map(self.normalize, classes) if classes else None

    self.flags = []
    if context.options.junit_run_xmlreport or context.options.junit_run_suppress_output:
      if context.options.junit_run_xmlreport:
        self.flags.append('-xmlreport=true')
      self.flags.append('-suppress-output=true')
      self.flags.append('-outdir=%s' % (context.options.junit_run_outdir or
                                        context.config.get('junit-run', 'workdir')))


  def execute(self, targets):
    if not self.context.options.junit_run_skip:
      tests = self.tests or self.calculate_tests(targets)
      if tests:
        classpath = profile_classpath(self.profile)

        # TODO(John Sirois): undo cheeseball! - derive src/resources from target attribute and then
        # later fix tests to declare their resources as well?
        classpath.extend(os.path.join(get_buildroot(), path)
                         for path in ('src/resources', 'tests/resources'))

        with self.context.state('classpath', []) as cp:
          classpath.extend(jar for conf, jar in cp if conf in self.confs)

        result = runjava(
          jvmargs=self.java_args,
          classpath=classpath,
          main='com.twitter.common.testing.runner.JUnitConsoleRunner',
          args=self.flags + list(tests)
        )
        if result != 0:
          raise TaskError()

  def calculate_tests(self, targets):
    def is_test_file(test):
      # TODO(John Sirois): config for a list of include regexes and exclude regexes
      basename = os.path.basename(test)
      return (test.endswith('Test.java') or test.endswith('IT.java')) \
          and not basename.startswith('Base') and not basename.startswith('Abstract')

    tests = set()
    for target in targets:
      if is_java(target) and is_test(target):
        tests.update(self.normalize(test, target.target_base) for test in target.sources
                     if is_test_file(test))
    return tests

  def normalize(self, classname_or_file, basedir=None):
    components = classname_or_file.split('#', 2)
    classname = components[0]
    methodname = '#' + components[1] if len(components) == 2 else ''

    if not classname.endswith('.java'):
      return classname + methodname

    def relpath_toclassname(path):
      return path.replace('/', '.').replace('.java', '')

    if basedir:
      return relpath_toclassname(classname) + methodname
    else:
      basedir = calculate_basedir(classname)
      return relpath_toclassname(os.path.relpath(classname, basedir)) + methodname


PACKAGE_PARSER = re.compile(r'^\s*package\s+([\w.]+)\s*;\s*')

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



