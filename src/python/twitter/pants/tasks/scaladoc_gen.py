# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

from twitter.pants import is_scala
from twitter.pants.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen

scaladoc = Jvmdoc(tool_name='scaladoc')


class ScaladocGen(JvmdocGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    cls.generate_setup_parser(option_group, args, mkflag, scaladoc)

  def __init__(self, context, output_dir=None, confs=None):
    super(ScaladocGen, self).__init__(context, scaladoc, output_dir, confs)

  def execute(self, targets):
    self.generate_execute(targets, is_scala, create_scaladoc_command)


def create_scaladoc_command(classpath, gendir, *targets):
  sources = []
  for target in targets:
    sources.extend(os.path.join(target.target_base, source) for source in target.sources)

  if not sources:
    return None

  # TODO(John Chee): try scala.tools.nsc.ScalaDoc via ng
  command = [
    'scaladoc',
    '-usejavacp',
    '-classpath', ':'.join(classpath),
    '-d', gendir,
  ]

  command.extend(sources)
  return command
