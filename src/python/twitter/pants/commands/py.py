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

__author__ = 'Brian Wickman'

import os
import signal

from . import Command

from twitter.common.python.pex import PEX

from twitter.pants import is_concrete
from twitter.pants.base import Address, Config, Target
from twitter.pants.targets import PythonBinary
from twitter.pants.python.python_chroot import PythonChroot
from twitter.pants.python.resolver import PythonResolver

class Py(Command):
  """Python chroot manipulation."""

  __command__ = 'py'

  def setup_parser(self, parser, args):
    parser.set_usage("\n"
                     "  %prog py (options) [spec] args\n")
    parser.disable_interspersed_args()
    parser.add_option("-t", "--timeout", dest="conn_timeout", type="int",
                      default=Config.load().getdefault('connection_timeout'),
                      help="Number of seconds to wait for http connections.")
    parser.add_option("--pex", dest="pex", default=False, action='store_true',
                      help="dump a .pex of this chroot")
    parser.add_option("--resolve", dest="resolve", default=False, action='store_true',
                      help="resolve targets instead of building.")
    parser.add_option("-v", "--verbose", dest="verbose", default=False, action='store_true',
                      help="show verbose output.")
    parser.epilog = """Interact with the chroot of the specified target."""

  def __init__(self, run_tracker, root_dir, parser, argv):
    Command.__init__(self, run_tracker, root_dir, parser, argv)

    if not self.args:
      self.error("A spec argument is required")

    self.target = None
    self.extra_targets = []

    # We parse each arg in the context of the cli usage:
    #   ./pants command (options) [spec] (build args)
    #   ./pants command (options) [spec]... -- (build args)
    # Our command token and our options are parsed out so we see args of the form:
    #   [spec] (build args)
    #   [spec]... -- (build args)
    for k in range(len(self.args)):
      arg = self.args.pop(0)
      if arg == '--':
        break

      target = None
      try:
        address = Address.parse(root_dir, arg)
        target = Target.get(address)
      except Exception:
        pass

      if not target:
        # We failed to parse the arg as a target or else it was in valid address format but did not
        # correspond to a real target.  Assume this is the 1st of the build args and terminate
        # processing args for target addresses.
        break

      binaries = []
      for resolved in filter(is_concrete, target.resolve()):
        if isinstance(resolved, PythonBinary):
          binaries.append(resolved)
        else:
          self.extra_targets.append(resolved)

      if not binaries:
        # No binary encountered yet so move on to the next spec to find one or else accumulate more
        # libraries for ./pants py -> interpreter mode.
        pass
      elif len(binaries) == 1:
        # We found a binary and are done, the rest of the args get passed to it
        self.target = binaries[0]
        break
      else:
        self.error('Can only process 1 binary target, %s contains %d:\n\t%s' % (
          arg, len(binaries), '\n\t'.join(str(binary.address) for binary in binaries)
        ))

    if self.target is None:
      if not self.extra_targets:
        self.error('No valid target specified!')
      self.target = self.extra_targets.pop(0)

  def execute(self):
    if self.options.verbose:
      print("Build operating on target: %s %s" % (self.target,
        'Extra targets: %s' % ' '.join(map(str, self.extra_targets)) if self.extra_targets else ''))

    if self.options.resolve:
      executor = PythonResolver([self.target] + self.extra_targets)
      executor.dump()
      return 0

    executor = PythonChroot(self.target, self.root_dir, extra_targets=self.extra_targets,
                            conn_timeout=self.options.conn_timeout)
    builder = executor.dump()
    if self.options.pex:
      pex_name = os.path.join(self.root_dir, 'dist', '%s.pex' % self.target.name)
      builder.build(pex_name)
      print('Wrote %s' % pex_name)
      return 0
    else:
      builder.freeze()
      pex = PEX(builder.path())
      po = pex.run(args=list(self.args), blocking=False)
      try:
        po.wait()
      except KeyboardInterrupt:
        po.send_signal(signal.SIGINT)
        raise
