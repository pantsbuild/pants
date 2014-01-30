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

import sys
import traceback

from twitter.common.collections import OrderedSet

from twitter.pants.base.address import Address
from twitter.pants.base.config import Config
from twitter.pants.base.target import Target
from twitter.pants.targets import InternalTarget
from twitter.pants.python import PythonBuilder
from twitter.pants.python.interpreter_cache import PythonInterpreterCache

from . import Command


class Build(Command):
  """Builds a specified target."""

  __command__ = 'build'

  def setup_parser(self, parser, args):
    parser.set_usage("\n"
                     "  %prog build (options) [spec] (build args)\n"
                     "  %prog build (options) [spec]... -- (build args)")
    parser.add_option("-t", "--timeout", dest="conn_timeout", type="int",
                      default=Config.load().getdefault('connection_timeout'),
                      help="Number of seconds to wait for http connections.")
    parser.add_option('-i', '--interpreter', dest='interpreter', default=None,
                      help='The interpreter requirement for this chroot.')
    parser.add_option('-v', '--verbose', dest='verbose', default=False, action='store_true',
                      help='Show verbose output.')
    parser.disable_interspersed_args()
    parser.epilog = ('Builds the specified Python target(s). Use ./pants goal for JVM and other '
                     'targets.')

  def __init__(self, run_tracker, root_dir, parser, argv):
    Command.__init__(self, run_tracker, root_dir, parser, argv)

    if not self.args:
      self.error("A spec argument is required")

    self.config = Config.load()
    self.interpreter_cache = PythonInterpreterCache(self.config, logger=self.debug)
    self.interpreter_cache.setup()
    interpreters = self.interpreter_cache.select_interpreter(
        list(self.interpreter_cache.matches([self.options.interpreter]
            if self.options.interpreter else [''])))
    if len(interpreters) != 1:
      self.error('Unable to detect suitable interpreter.')
    else:
      self.debug('Selected %s' % interpreters[0])
    self.interpreter = interpreters[0]

    try:
      specs_end = self.args.index('--')
      if len(self.args) > specs_end:
        self.build_args = self.args[specs_end+1:len(self.args)+1]
      else:
        self.build_args = []
    except ValueError:
      specs_end = 1
      self.build_args = self.args[1:] if len(self.args) > 1 else []

    self.targets = OrderedSet()
    for spec in self.args[0:specs_end]:
      try:
        address = Address.parse(root_dir, spec)
      except:
        self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))

      try:
        target = Target.get(address)
      except:
        self.error("Problem parsing BUILD target %s: %s" % (address, traceback.format_exc()))

      if not target:
        self.error("Target %s does not exist" % address)
      self.targets.update(tgt for tgt in target.resolve() if tgt.is_concrete)

  def debug(self, message):
    if self.options.verbose:
      print(message, file=sys.stderr)

  def execute(self):
    print("Build operating on targets: %s" % self.targets)

    python_targets = OrderedSet()
    for target in self.targets:
      if target.is_python:
        python_targets.add(target)
      else:
        self.error("Cannot build target %s" % target)

    if python_targets:
      status = self._python_build(python_targets)
    else:
      status = -1

    return status

  def _python_build(self, targets):
    try:
      executor = PythonBuilder(self.run_tracker, self.root_dir)
      return executor.build(
        targets,
        self.build_args,
        interpreter=self.interpreter,
        conn_timeout=self.options.conn_timeout)
    except:
      self.error("Problem executing PythonBuilder for targets %s: %s" % (targets,
                                                                         traceback.format_exc()))
