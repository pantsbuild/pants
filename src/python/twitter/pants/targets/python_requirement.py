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

__author__ = 'Brian Wickman'

from pkg_resources import Requirement
from twitter.pants.targets.python_target import PythonTarget

class PythonRequirement(PythonTarget):
  """Egg equivalence classes"""

  def __init__(self, requirement, name=None):
    self._requirement = Requirement.parse(requirement)
    self._name = name or self._requirement.project_name

    PythonTarget.__init__(self,
      name = self._name,
      sources = None,
      dependencies = None)

  def size(self):
    return 1

  def __repr__(self):
    return 'PythonRequirement(%s)' % self._requirement
