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

__author__ = 'Benjy Weinberger'

import shlex

from twitter.pants.targets import JavaLibrary, JavaTests, ScalaLibrary, ScalaTests
from twitter.pants.tasks import Task
from twitter.pants.tasks.binary_utils import profile_classpath, runjava
from twitter.pants.tasks.jvm_task import JvmTask


class ScalaRepl(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest = "run_jvmargs", action="append",
      help = "Run the repl in a jvm with these extra jvm args.")
    option_group.add_option(mkflag("args"), dest = "run_args", action="append",
                            help = "run the repl in a jvm with extra args.")

  def __init__(self, context):
    Task.__init__(self, context)
    self.jvm_args = context.config.getlist('scala-repl', 'jvm_args', default=[])
    if context.options.run_jvmargs:
      for arg in context.options.run_jvmargs:
        self.jvm_args.extend(shlex.split(arg))
    self.confs = context.config.getlist('scala-repl', 'confs')
    self.profile = context.config.get('scala-repl', 'profile')
    self.main = context.config.get('scala-repl', 'main')
    self.args = context.config.getlist('scala-repl', 'args', default=[])
    if context.options.run_args:
      for arg in context.options.run_args:
        self.args.extend(shlex.split(arg))

  def execute(self, targets):
    runjava(
      jvmargs=self.jvm_args,
      classpath=self.classpath(profile_classpath(self.profile), confs=self.confs),
      main=self.main,
      args=self.args
    )

