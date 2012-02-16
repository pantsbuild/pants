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

import os
import traceback

from twitter.pants.base import Address, Target
from twitter.pants.commands import Command

class Files(Command):
  """Lists all source files owned by the given target."""

  __command__ = 'files'

  def setup_parser(self, parser, args):
    parser.set_usage("%prog files [spec]")
    parser.epilog = """Lists all source files owned by the given BUILD target."""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    if len(self.args) is not 1:
      self.error("Exactly one BUILD address is required.")

    spec = self.args[0]
    try:
      address = Address.parse(root_dir, spec)
    except IOError:
      self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))

    try:
      self.target = Target.get(address)
    except (ImportError, SyntaxError, TypeError):
      self.error("Problem parsing BUILD target %s: %s" % (address, traceback.format_exc()))

    if not self.target:
        self.error("Target %s does not exist" % address)

  def execute(self):
    for target in self.target.resolve():
      for sourcefile in getattr(target, 'sources', ()) or ():
        print os.path.join(target.target_base, sourcefile)

      for resourcefile in getattr(target, 'resources', ()) or ():
        # TODO(John Sirois): fill resource source_root hole to get a full path from the build
        # root here
        print '[res] %s' % resourcefile

      for java_source in getattr(target, 'java_sources', ()) or ():
        # TODO(John Sirois): fill java_sources source_root hole to get a full path from the build
        # root here
        print '[java cyclic] %s' % java_source
