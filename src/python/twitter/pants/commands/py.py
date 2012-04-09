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

from . import Command

from twitter.common.python.pex import PEX

from twitter.pants.base import Address, Target
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
    parser.add_option("--pex", dest = "pex", default = False, action='store_true',
                      help = "dump a .pex of this chroot")
    parser.add_option("--resolve", dest = "resolve", default = False, action='store_true',
                      help = "resolve targets instead of building.")
    parser.epilog = """Interact with the chroot of the specified target."""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    if not self.args:
      self.error("A spec argument is required")

    targets = []

    # TODO(wickman)  Ignore the -- crap
    for k in range(len(self.args)):
      arg = self.args[0]
      if arg == '--':
        self.args.pop(0)
        break

      try:
        address = Address.parse(root_dir, arg)
        target = Target.get(address)
      except Exception as e:
        break
      if not target:
        break

      targets.append(target)
      self.args.pop(0)

      # stop at PythonBinary target
      if isinstance(target, PythonBinary):
        break

    self.target = targets.pop(0) if targets else None
    self.extra_targets = targets

    if self.target is None:
      self.error('No valid target specified!')

  def execute(self):
    print("Build operating on target: %s %s" % (self.target,
      'Extra targets: %s' % ' '.join(map(str, self.extra_targets)) if self.extra_targets else ''))

    if self.options.resolve:
      executor = PythonResolver(self.target, self.root_dir, extra_targets=self.extra_targets)
      executor.dump()
      return 0

    executor = PythonChroot(self.target, self.root_dir, extra_targets=self.extra_targets)
    builder = executor.dump()
    if self.options.pex:
      pex_name = os.path.join(self.root_dir, 'dist', '%s.pex' % self.target.name)
      builder.build(pex_name)
      print('Wrote %s' % pex_name)
      return 0
    else:
      builder.freeze()
      pex = PEX(builder.path())
      return pex.run(args=list(self.args))
