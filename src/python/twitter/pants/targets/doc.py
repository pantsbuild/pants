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

__author__ = 'Mark McBride'

from internal import InternalTarget
from with_sources import TargetWithSources

class Doc(InternalTarget, TargetWithSources):
  """A target that processes documentation in a directory"""
  def __init__(self, name, dependencies=(), sources=None, resources=None):
    InternalTarget.__init__(self, name, dependencies, None)
    TargetWithSources.__init__(self, name)
    if not sources:
      raise TargetDefinitionException(self, 'No sources specified')
    self.name = name
    self.sources = self._resolve_paths(self.target_base, sources)
    self.resources = self._resolve_paths(self.target_base, resources)
