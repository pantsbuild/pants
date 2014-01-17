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
from twitter.pants.base import Target
from .external_dependency import ExternalDependency

class PythonRequirement(Target, ExternalDependency):
  """Pants wrapper around pkg_resources.Requirement"""

  def __init__(self, requirement, dynamic=False, repository=None, name=None, version_filter=None,
              exclusives=None):
    self._requirement = Requirement.parse(requirement)
    self._name = name or self._requirement.project_name
    self._dynamic = dynamic
    self._repository = repository
    self._version_filter = version_filter or (lambda: True)
    Target.__init__(self, self._name, exclusives=exclusives)

  def size(self):
    return 1

  def should_build(self):
    return self._version_filter()

  def cache_key(self):
    return str(self._requirement)

  def __repr__(self):
    return 'PythonRequirement(%s)' % self._requirement
