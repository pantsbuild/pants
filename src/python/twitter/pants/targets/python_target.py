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

from collections import defaultdict

from twitter.common.collections import OrderedSet
from twitter.common.python.interpreter import PythonIdentity

from twitter.pants.base.target import Target, TargetDefinitionException

from .with_dependencies import TargetWithDependencies
from .with_sources import TargetWithSources


class PythonTarget(TargetWithDependencies, TargetWithSources):
  """Base class for all Python targets."""

  def __init__(self,
               name,
               sources,
               resources=None,
               dependencies=None,
               provides=None,
               compatibility=None,
               exclusives=None):
    TargetWithSources.__init__(self, name, sources=sources, exclusives=exclusives)
    TargetWithDependencies.__init__(self, name, dependencies=dependencies, exclusives=exclusives)

    self.add_labels('python')
    self.resources = self._resolve_paths(resources) if resources else OrderedSet()
    self.provides = provides
    self.compatibility = compatibility or ['']
    for req in self.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(str(e))

  def _walk(self, walked, work, predicate=None):
    super(PythonTarget, self)._walk(walked, work, predicate)
    if self.provides and self.provides.binaries:
      for binary in self.provides.binaries.values():
        binary._walk(walked, work, predicate)

  def _propagate_exclusives(self):
    self.exclusives = defaultdict(set)
    for k in self.declared_exclusives:
      self.exclusives[k] = self.declared_exclusives[k]
    for t in self.dependencies:
      if isinstance(t, Target):
        t._propagate_exclusives()
        self.add_to_exclusives(t.exclusives)
      elif hasattr(t, "declared_exclusives"):
        self.add_to_exclusives(t.declared_exclusives)
