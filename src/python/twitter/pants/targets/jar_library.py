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

from twitter.pants.base import Target

class JarLibrary(Target):
  """Serves as a proxy for one or more JarDependencies or JavaTargets."""

  def __init__(self, name, dependencies):
    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    dependencies: one or more JarDependencies this JarLibrary bundles or Pants pointing to other
        JarLibraries or JavaTargets"""

    assert len(dependencies) > 0, "At least one dependency must be specified"
    Target.__init__(self, name, False)

    self.dependencies = dependencies

  def resolve(self):
    for dependency in self.dependencies:
      for resolved_dependency in dependency.resolve():
        yield resolved_dependency
