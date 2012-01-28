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

from . import Command

from copy import copy

class Help(Command):
  """Provides help for available commands or a single specified command."""

  __command__ = 'help'

  def setup_parser(self, parser, args):
    self.parser = copy(parser)

    parser.set_usage("%prog help ([command])")
    parser.epilog = """Lists available commands with no arguments; otherwise prints help for the
                    specifed command."""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    if len(self.args) > 1:
      self.error("The help command accepts at most 1 argument.")
    self.subcommand = self.args[0]

  def execute(self):
    subcommand_class = Command.get_command(self.subcommand)

    command = subcommand_class(self.root_dir, self.parser, [ '--help' ])
    return command.execute()
