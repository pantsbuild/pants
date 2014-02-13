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

from .jvm_target import JvmTarget
from .resources import Resources


class ScalaTests(JvmTarget):
  """Defines a target that tests a scala library."""

  def __init__(self, name, sources=None, java_sources=None, dependencies=None, excludes=None,
               resources=None, buildflags=None, exclusives=None):
    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the scala source files this modules tests are compiled from.
    java_sources: An optional JavaLibrary target or list of targets containing the java libraries
        this library has a circular dependency on.  Prefer using dependencies to express
        non-circular dependencies.
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    resources: An optional list of Resources that should be in this target's classpath.
    buildflags: DEPRECATED - A list of additional command line arguments to pass to the underlying
        build system for this target - now ignored.
    exclusives:   An optional map of exclusives tags. See CheckExclusives for details.
    """

    JvmTarget.__init__(self, name, sources, dependencies, excludes, exclusives=exclusives)

    self.add_labels('scala', 'tests')
    self.java_sources = java_sources
    self.resources = list(self.resolve_all(resources, Resources))
