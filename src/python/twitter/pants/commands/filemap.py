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

__author__ = 'John Sirois'

from . import Command

from twitter.pants.base import BuildFile, Target

class Filemap(Command):
  """Outputs a mapping from source file to the target that owns the source file."""

  __command__ = 'filemap'

  def setup_parser(self, parser, args):
    parser.set_usage("%prog filemap")
    parser.epilog = """Outputs a mapping from source file to the target that owns the source file.
    The mapping is output in 2 columns."""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    if self.args:
      self.error("The filemap subcommand accepts no arguments.")

  def execute(self):
    for buildfile in BuildFile.scan_buildfiles(self.root_dir):
      for address in Target.get_all_addresses(buildfile):
        target = Target.get(address)
        if hasattr(target, 'sources') and target.sources is not None:
          for sourcefile in target.sources:
            print(sourcefile, address)
