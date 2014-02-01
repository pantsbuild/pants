# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

from twitter.common.util import topological_sort

from .console_task import ConsoleTask
from ..base import Target


class SortTargets(ConsoleTask):
  @staticmethod
  def _is_target(item):
    return isinstance(item, Target)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(SortTargets, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("reverse"), mkflag("reverse", negate=True),
                            dest="sort_targets_reverse", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Sort least depenendent to most.")

  def __init__(self, *args, **kwargs):
    super(SortTargets, self).__init__(*args, **kwargs)
    self._reverse = self.context.options.sort_targets_reverse

  def console_output(self, targets):
    depmap = defaultdict(set)

    def map_deps(target):
      # TODO(John Sirois): rationalize target hierarchies - this is the only 'safe' way to treat
      # both python and jvm targets today.
      if hasattr(target, 'dependencies'):
        deps = depmap[str(target.address)]
        for dep in target.dependencies:
          for resolved in filter(self._is_target, dep.resolve()):
            deps.add(str(resolved.address))

    for root in self.context.target_roots:
      root.walk(map_deps, self._is_target)

    tsorted = []
    for group in topological_sort(depmap):
      tsorted.extend(group)
    if self._reverse:
      tsorted = reversed(tsorted)

    roots = set(str(root.address) for root in self.context.target_roots)
    for address in tsorted:
      if address in roots:
        yield address
