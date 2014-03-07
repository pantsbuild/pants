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

import os

from twitter.common.lang import Compatibility
from twitter.common.log import logger
from twitter.pants.base.config import Config


log = logger(name='rcfile')


class RcFile(object):
  """Handles rcfile-style configuration files.

  Precedence is given to rcfiles that come last in the given sequence of paths.
  The effect is as if each rcfile in paths overlays the next in a walk from left to right.
  """

  # TODO(John Sirois): localize handling of this flag value back into pants_exe.py once the new old
  # split is healed.
  _DISABLE_PANTS_RC_OPTION = '--no-pantsrc'

  @staticmethod
  def install_disable_rc_option(parser):
    parser.add_option(RcFile._DISABLE_PANTS_RC_OPTION, action = 'store_true', dest = 'nopantsrc',
                      default = False, help = 'Specifies that pantsrc files should be ignored.')

  def __init__(self, paths, default_prepend=True, process_default=False):
    """
    :param paths: The rcfiles to apply default subcommand options from.
    :param default_prepend: Whether to prepend (the default) or append if default options
      are specified with the ``options`` key.
    :param process_default: True to process options in the [DEFAULT] section and apply
      regardless of goal.
    """

    self.default_prepend = default_prepend
    self.process_default = process_default

    if not paths:
      raise ValueError('One or more rcfile paths must be specified')

    if isinstance(paths, Compatibility.string):
      paths = [paths]
    self.paths = [os.path.expanduser(path) for path in paths]

  def apply_defaults(self, commands, args):
    """Augment arguments with defaults found for the given commands.

    The returned arguments will be a new copy of the given args with possibly extra augmented
    arguments.

    Default options are applied from the following keys under a section with the name of the
    sub-command the default options apply to:

    * `options` - These options are either prepended or appended to the command line args as
      specified in the constructor with default_prepend.
    * `prepend-options` - These options are prepended to the command line args.
    * `append-options` - These options are appended to the command line args.
    """

    args = args[:]

    if RcFile._DISABLE_PANTS_RC_OPTION in args:
      return args

    config = Config.create_parser()
    read_from = config.read(self.paths)
    if not read_from:
      log.debug('no rcfile found')
      return args

    log.debug('using rcfiles: %s to modify args' % ','.join(read_from))

    def get_rcopts(command, key):
      return config.get(command, key).split() if config.has_option(command, key) else []

    commands = list(commands)
    if self.process_default:
      commands.insert(0, Config.DEFAULT_SECTION)

    for cmd in commands:
      opts = get_rcopts(cmd, 'options')
      args = (opts + args) if self.default_prepend else (args + opts)
      args = get_rcopts(cmd, 'prepend-options') + args + get_rcopts(cmd, 'append-options')
    return args
