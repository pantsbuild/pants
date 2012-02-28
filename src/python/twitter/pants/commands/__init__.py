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

from __future__ import print_function

import inspect
import sys

from twitter.common.collections import OrderedSet
from twitter.pants.base import BuildFile, Target

class Command:
  """Baseclass for all pants subcommands."""

  @staticmethod
  def get_command(name):
    return Command._commands.get(name, None)

  @staticmethod
  def all_commands():
    return Command._commands.keys()

  _commands = {}

  @staticmethod
  def _register_modules():
    import pkgutil
    for _, mod, ispkg in pkgutil.iter_modules(__path__):
      if ispkg: continue
      fq_module = '.'.join([__name__, mod])
      __import__(fq_module)
      for (_, kls) in inspect.getmembers(sys.modules[fq_module], inspect.isclass):
        if issubclass(kls, Command):
          command_name = kls.__dict__.get('__command__', None)
          if command_name:
            Command._commands[command_name] = kls

  @staticmethod
  def scan_addresses(root_dir, base_path = None):
    """Parses all targets available in BUILD files under base_path and
    returns their addresses.  If no base_path is specified, root_dir is
    assumed to be the base_path"""

    addresses = OrderedSet()
    for buildfile in BuildFile.scan_buildfiles(root_dir, base_path):
      addresses.update(Target.get_all_addresses(buildfile))
    return addresses

  def __init__(self, root_dir, parser, args):
    """root_dir: The root directory of the pants workspace
    parser: an OptionParser
    argv: the subcommand arguments to parse"""

    self.root_dir = root_dir

    # Override the OptionParser's error with more useful output
    def error(message = None):
      if message:
        print(message + '\n')
      parser.print_help()
      parser.exit(status = 1)
    parser.error = error
    self.error = error

    self.setup_parser(parser, args)
    self.options, self.args = parser.parse_args(args)
    self.parser = parser

  def setup_parser(self, parser, args):
    """Subclasses should override and confiure the OptionParser to reflect
    the subcommand option and argument requirements.  Upon successful
    construction, subcommands will be able to access self.options and
    self.args."""

    pass

  def error(self, message = None):
    """Reports the error message followed by pants help and then exits."""

  def execute(self):
    """Subcommands should override to perform the command action.  The value
    returned should be an int, 0 indicating success and any other value
    indicating failure."""

    pass

Command._register_modules()
