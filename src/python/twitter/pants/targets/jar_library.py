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

from twitter.pants.base import Target, TargetDefinitionException

from .util import resolve


class JarLibrary(Target):
  """Serves as a proxy for one or more JarDependencies or JavaTargets."""

  def __init__(self, name, dependencies, exclusives=None):
    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    dependencies: one or more JarDependencies this JarLibrary bundles or Pants pointing to other
        JarLibraries or JavaTargets
    exclusives:   An optional map of exclusives tags. See CheckExclusives for details.
    """
    Target.__init__(self, name, exclusives=exclusives)

    if dependencies is None:
      raise TargetDefinitionException(self, "A dependencies list must be supplied even if empty.")
    self.add_labels('jars')
    self.dependencies = resolve(dependencies)
    self.dependency_addresses = set()
    for dependency in self.dependencies:
      if hasattr(dependency, 'address'):
        self.dependency_addresses.add(dependency.address)
      # If the dependency is one that supports exclusives, the JarLibrary's
      # exclusives should be added to it.
      if hasattr(dependency, 'declared_exclusives'):
        for k in self.declared_exclusives:
          dependency.declared_exclusives[k] |= self.declared_exclusives[k]

  def resolve(self):
    yield self
    for dependency in self.dependencies:
      for resolved_dependency in dependency.resolve():
        yield resolved_dependency
