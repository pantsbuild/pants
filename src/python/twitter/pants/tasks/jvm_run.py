# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import shlex

from twitter.common.dirutil import safe_open
from twitter.pants.base.workunit import WorkUnit
from twitter.pants.java.executor import CommandLineGrabber
from twitter.pants.targets import JvmBinary
from twitter.pants.java.util import execute_java

from .jvm_task import JvmTask

from . import Task, TaskError


def is_binary(target):
  return isinstance(target, JvmBinary)


class JvmRun(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest = "run_jvmargs", action="append",
      help = "Run binary in a jvm with these extra jvm args.")

    option_group.add_option(mkflag("args"), dest = "run_args", action="append",
      help = "Run binary with these main() args.")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True), dest = "run_debug",
      action="callback", callback=mkflag.set_bool, default=False,
      help = "[%default] Run binary with a debugger")

    option_group.add_option(mkflag('only-write-cmd-line'), dest = 'only_write_cmd_line',
                            action='store', default=None,
                            help = '[%default] Instead of running, just write the cmd line to this file')

  def __init__(self, context):
    Task.__init__(self, context)
    self.jvm_args = context.config.getlist('jvm-run', 'jvm_args', default=[])
    if context.options.run_jvmargs:
      for arg in context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.args = []
    if context.options.run_args:
      for arg in context.options.run_args:
        self.args.extend(shlex.split(arg))
    if context.options.run_debug:
      self.jvm_args.extend(context.config.getlist('jvm', 'debug_args'))
    self.confs = context.config.getlist('jvm-run', 'confs')
    self.only_write_cmd_line = context.options.only_write_cmd_line
    context.products.require_data('exclusives_groups')

  def execute(self, targets):
    # The called binary may block for a while, allow concurrent pants activity during this pants
    # idle period.
    #
    # TODO(John Sirois): refactor lock so that I can do:
    # with self.context.lock.yield():
    #   - blocking code
    #
    # Currently re-acquiring the lock requires a path argument that was set up by the goal
    # execution engine.  I do not want task code to learn the lock location.
    # http://jira.local.twitter.com/browse/AWESOME-1317

    self.context.lock.release()
    # Run the first target that is a binary.
    binaries = filter(is_binary, targets)
    if len(binaries) > 0:  # We only run the first one.
      main = binaries[0].main
      egroups = self.context.products.get_data('exclusives_groups')
      group_key = egroups.get_group_key_for_target(binaries[0])
      group_classpath = egroups.get_classpath_for_group(group_key)

      executor = CommandLineGrabber() if self.only_write_cmd_line else None
      result = execute_java(
        classpath=(self.classpath(confs=self.confs, exclusives_classpath=group_classpath)),
        main=main,
        executor=executor,
        jvm_options=self.jvm_args,
        args=self.args,
        workunit_factory=self.context.new_workunit,
        workunit_name='run',
        workunit_labels=[WorkUnit.RUN]
      )

      if self.only_write_cmd_line:
        with safe_open(self.only_write_cmd_line, 'w') as outfile:
          outfile.write(executor.cmd)
      elif result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (main, result), exit_code=result)
