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

from collections import defaultdict

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base.target import Target
from twitter.pants.base.build_file import BuildFile
from twitter.pants.tasks.console_task import ConsoleTask


class ReverseDepmap(ConsoleTask):
  """Outputs all targets whose dependencies include at least one of the input targets."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ReverseDepmap, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
                            dest="reverse_depmap_transitive", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] List transitive dependees.")

    option_group.add_option(mkflag("closed"), mkflag("closed", negate=True),
                            dest="reverse_depmap_closed", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Include the input targets in the output along with "
                                 "the dependees.")

  def __init__(self, context):
    ConsoleTask.__init__(self, context)

    self._transitive = context.options.reverse_depmap_transitive
    self._closed = context.options.reverse_depmap_closed

  def console_output(self, _):
    dependees_by_target = defaultdict(set)
    for buildfile in BuildFile.scan_buildfiles(get_buildroot()):
      for address in Target.get_all_addresses(buildfile):
        for target in Target.get(address).resolve():
          if hasattr(target, 'dependencies'):
            for dependencies in target.dependencies:
              for dependency in dependencies.resolve():
                dependees_by_target[dependency].add(target)

    roots = set(self.context.target_roots)
    if self._closed:
      for root in roots:
        yield str(root.address)

    for dependant in self.get_dependants(dependees_by_target, roots):
      yield str(dependant.address)

  def get_dependants(self, dependees_by_target, roots):
    check = set(roots)
    known_dependants = set()
    while True:
      dependants = set(known_dependants)
      for target in check:
        dependants.update(dependees_by_target[target])
      check = dependants - known_dependants
      if not check or not self._transitive:
        return dependants - set(roots)
      known_dependants = dependants
