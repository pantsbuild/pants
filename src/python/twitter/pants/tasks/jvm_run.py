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


from twitter.common.collections.orderedset import OrderedSet
from twitter.pants.targets import JvmBinary
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.binary_utils import runjava


def is_binary(target):
  return isinstance(target, JvmBinary)


class JvmRun(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("jvmargs"), dest = "run_jvmargs", action="append",
      help = "Run binary in a jvm with these extra jvm args.")

    option_group.add_option(mkflag("args"), dest = "run_args", action="append",
      help = "Run binary with these main() args.")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True), dest = "run_debug",
      action="callback", callback=mkflag.set_bool, default=False,
      help = "[%default] Run binary with a debugger")


  def __init__(self, context):
    Task.__init__(self, context)
    self.context.products.require('classes')
    self.jvm_args = context.config.getlist('run', 'jvm_args', default=[])
    if context.options.run_jvmargs:
      self.jvm_args.extend(context.options.run_jvmargs)
    self.args = []
    if context.options.run_args:
      self.args.extend(context.options.run_args)
    if context.options.run_debug:
      self.jvm_args.extend(context.config.getlist('jvm', 'debug_args'))
    self.confs = context.config.getlist('run', 'confs')

  def execute(self, targets):
    # Run the first target that is a binary.
    binaries = filter(is_binary, targets)
    if len(binaries) > 0:  # We only run the first one.
      main = binaries[0].main
      classpath = []
      with self.context.state('classpath', []) as cp:
        classpath.extend(jar for conf, jar in cp if conf in self.confs)

      result = runjava(
        jvmargs=self.jvm_args,
        classpath=classpath,
        main=main,
        args=self.args
      )
      if result != 0:
        raise TaskError()






