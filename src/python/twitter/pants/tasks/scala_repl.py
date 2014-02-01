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
import subprocess

from twitter.pants.base.workunit import WorkUnit
from twitter.pants.java.util import execute_java
from .jvm_task import JvmTask

from . import Task


class ScalaRepl(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest = "run_jvmargs", action="append",
      help = "Run the repl in a jvm with these extra jvm args.")
    option_group.add_option(mkflag('args'), dest = 'run_args', action='append',
                            help = 'run the repl in a jvm with extra args.')

  def __init__(self, context):
    Task.__init__(self, context)
    self.jvm_args = context.config.getlist('scala-repl', 'jvm_args', default=[])
    if context.options.run_jvmargs:
      for arg in context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.confs = context.config.getlist('scala-repl', 'confs')
    self._bootstrap_key = 'scala-repl'
    bootstrap_tools = context.config.getlist('scala-repl', 'bootstrap-tools')
    self._jvm_tool_bootstrapper.register_jvm_tool(self._bootstrap_key, bootstrap_tools)
    self.main = context.config.get('scala-repl', 'main')
    self.args = context.config.getlist('scala-repl', 'args', default=[])
    if context.options.run_args:
      for arg in context.options.run_args:
        self.args.extend(shlex.split(arg))

  def execute(self, targets):
    # The repl session may last a while, allow concurrent pants activity during this pants idle
    # period.
    tools_classpath = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._bootstrap_key)

    self.context.lock.release()
    self.save_stty_options()

    classpath = self.classpath(tools_classpath,
                               confs=self.confs,
                               exclusives_classpath=self.get_base_classpath_for_target(targets[0]))

    print('')  # Start REPL output on a new line.
    try:
      execute_java(classpath=classpath,
                   main=self.main,
                   jvm_options=self.jvm_args,
                   args=self.args,
                   workunit_factory=self.context.new_workunit,
                   workunit_name='repl',
                   workunit_labels=[WorkUnit.REPL, WorkUnit.JVM])
    except KeyboardInterrupt:
      # TODO(John Sirois): Confirm with Steve Gury that finally does not work on mac and an
      # explicit catch of KeyboardInterrupt is required.
      pass
    self.restore_ssty_options()

  def save_stty_options(self):
    """
    The scala REPL changes some stty parameters and doesn't save/restore them after
    execution, so if you have a terminal with non-default stty options, you end
    up to a broken terminal (need to do a 'reset').
    """
    self.stty_options = self.run_cmd('stty -g 2>/dev/null')

  def restore_ssty_options(self):
    self.run_cmd('stty ' + self.stty_options)

  def run_cmd(self, cmd):
    po = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    stdout, _ = po.communicate()
    return stdout
