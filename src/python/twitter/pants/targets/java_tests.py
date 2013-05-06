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


class JavaTests(JvmTarget):
  """Defines a target that tests a java library."""

  def __init__(self, name, sources=None, dependencies=None, excludes=None, resources=None,
               buildflags=None):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the java source files this modules tests are compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    resources: An optional list of Resources that should be in this target's classpath.
    buildflags: DEPRECATED - A list of additional command line arguments to pass to the underlying
        build system for this target - now ignored.
    """

    JvmTarget.__init__(self, name, sources, dependencies, excludes)
    self.add_labels('java', 'tests')
    self.resources = list(self.resolve_all(resources, Resources))
