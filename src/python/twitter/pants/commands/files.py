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

from twitter.pants.base import Address, Target

import traceback

class Files(Command):
  """Lists all source files owned by the given target."""

  __command__ = 'files'

  def setup_parser(self, parser):
    parser.set_usage("%prog files [spec]")
    parser.epilog = """Lists all source files owned by the given BUILD target."""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    if len(self.args) is not 1:
      self.error("Exactly one BUILD address is required.")

    spec = self.args[0]
    try:
      address = Address.parse(root_dir, spec)
    except:
      self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))

    try:
      self.target = Target.get(address)
    except:
      self.error("Problem parsing BUILD target %s: %s" % (address, traceback.format_exc()))

    if not self.target:
        self.error("Target %s does not exist" % address)

  def execute(self):
    for sourcefile in self.target.sources:
      print sourcefile
