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

from twitter.pants.base import Target

from .external_dependency import ExternalDependency

from pkg_resources import Requirement


class PythonRequirement(Target, ExternalDependency):
  """Pants wrapper around pkg_resources.Requirement"""

  def __init__(self, requirement, name=None, repository=None, version_filter=None, use_2to3=False,
               compatibility=None):
    # TODO(wickman) Allow PythonRequirements to be specified using pip-style vcs or url identifiers,
    # e.g. git+https or just http://...
    self._requirement = Requirement.parse(requirement)
    self._repository = repository
    self._name = name or self._requirement.project_name
    self._use_2to3 = use_2to3
    self._version_filter = version_filter or (lambda py, pl: True)
    # TODO(wickman) Unify this with PythonTarget .compatibility
    self.compatibility = compatibility or ['']
    Target.__init__(self, self._name)

  def should_build(self, python, platform):
    return self._version_filter(python, platform)

  @property
  def use_2to3(self):
    return self._use_2to3

  @property
  def repository(self):
    return self._repository

  # duck-typing Requirement interface for Resolver, since Requirement cannot be
  # subclassed (curses!)
  @property
  def key(self):
    return self._requirement.key

  @property
  def extras(self):
    return self._requirement.extras

  @property
  def specs(self):
    return self._requirement.specs

  @property
  def project_name(self):
    return self._requirement.project_name

  @property
  def requirement(self):
    return self._requirement

  def __contains__(self, item):
    return item in self._requirement

  def cache_key(self):
    return str(self._requirement)

  def __repr__(self):
    return 'PythonRequirement(%s)' % self._requirement
