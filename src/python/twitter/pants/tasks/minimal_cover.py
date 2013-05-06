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

from twitter.pants.tasks.console_task import ConsoleTask


class MinimalCover(ConsoleTask):
  """Outputs a minimal covering set of targets.

  For a given set of input targets, the output targets transitive dependency set will include all
  the input targets without gaps.
  """

  def console_output(self, _):
    internal_deps = set()
    for target in self.context.target_roots:
      internal_deps.update(self._collect_internal_deps(target))

    minimal_cover = set()
    for target in self.context.target_roots:
      if target not in internal_deps and target not in minimal_cover:
        minimal_cover.add(target)
        yield str(target.address)

  def _collect_internal_deps(self, target):
    internal_deps = set()
    target.walk(internal_deps.add)
    internal_deps.discard(target)
    return internal_deps
