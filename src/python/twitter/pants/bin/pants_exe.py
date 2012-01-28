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

from twitter.pants import get_buildroot, get_version
from twitter.pants.base import Address
from twitter.pants.commands import Command

import ConfigParser
import optparse
import os
import sys
import traceback

_HELP_ALIASES = set([
  '-h',
  '--help',
  'help',
])

_BUILD_COMMAND = 'build'

# Support legacy pants invocation syntax when the only subcommand was Build and the spec was
# supplied as an option instead of an argument
_BUILD_ALIASES = set([
  '-s',
  '--spec',
  '-f',
])

_DISABLE_PANTS_RC_OPTION = '--no-pantsrc'

def exit_and_fail(msg=''):
  print >> sys.stderr, msg
  sys.exit(1)

def find_all_commands():
  for cmd in Command.all_commands():
    cls = Command.get_command(cmd)
    yield '%s\t%s' % (cmd, cls.__doc__)

def _help(version, root_dir):
  print 'Pants %s @ PANTS_BUILD_ROOT: %s' % (version, root_dir)
  print
  print 'Available subcommands:\n\t%s' % '\n\t'.join(find_all_commands())
  print
  print """Default subcommand flags can be stored in ~/.pantsrc using the 'options' key of a
section named for the subcommand in ini style format, ie:
  [build]
  options: --fast"""
  sys.exit(0)

def _prepend_default_options(command, args):
  if _DISABLE_PANTS_RC_OPTION not in args:
    pantsrc = os.path.join(os.path.expanduser('~'), '.pantsrc')
    if os.path.exists(pantsrc):
      config = ConfigParser.SafeConfigParser()
      config.read(pantsrc)
      if config.has_option(command, 'options'):
        expanded_options = config.get(command, 'options').split() + args
        print "(using ~/.pantsrc expansion: pants %s %s)" % (command, ' '.join(expanded_options))
        return expanded_options
  return args

def _synthesize_command(root_dir, args):
  command = args[0]

  command = _BUILD_COMMAND if command in _BUILD_ALIASES else command
  if command in Command.all_commands():
    subcommand_args = args[1:] if len(args) > 1 else []
    return command, _prepend_default_options(command, subcommand_args)

  if command.startswith('-'):
    exit_and_fail('Invalid command: %s' % command)

  # assume 'build' if a command was ommitted.
  try:
    Address.parse(root_dir, command)
    return _BUILD_COMMAND, _prepend_default_options(_BUILD_COMMAND, args)
  except:
    exit_and_fail('Failed to execute pants build: %s' % traceback.format_exc())

def _parse_command(root_dir, args):
  command, args = _synthesize_command(root_dir, args)
  return Command.get_command(command), args

def main():
  root_dir = get_buildroot()
  version = get_version()

  if not os.path.exists(root_dir):
    exit_and_fail('PANTS_BUILD_ROOT does not point to a valid path: %s' % root_dir)

  if len(sys.argv) < 2 or (len(sys.argv) == 2 and sys.argv[1] in _HELP_ALIASES):
    _help(version, root_dir)

  command_class, command_args = _parse_command(root_dir, sys.argv[1:])

  parser = optparse.OptionParser(version = '%%prog %s' % version)
  parser.add_option(_DISABLE_PANTS_RC_OPTION, action = 'store_false', dest = 'pantsrc',
                    default = True, help = 'Specifies that ~/.pantsrc should be ignored.')
  command = command_class(root_dir, parser, command_args)

  result = command.execute()
  sys.exit(result)

if __name__ == '__main__':
  main()
