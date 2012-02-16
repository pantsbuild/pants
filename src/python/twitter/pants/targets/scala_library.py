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

import os

from twitter.common.collections import OrderedSet
from twitter.pants.targets import resolve_target_sources

from pants_target import Pants
from exportable_jvm_library import ExportableJvmLibrary

class ScalaLibrary(ExportableJvmLibrary):
  """Defines a target that produces a scala library."""

  def __init__(self, name,
               sources = None,
               java_sources = None,
               provides = None,
               dependencies = None,
               excludes = None,
               resources = None,
               deployjar = False,
               buildflags = None,
               is_meta = False):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the scala source files this module's jar is compiled from
    java_sources: An optional list of paths containing the java sources this module's jar is in part
        compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    resources: An optional list of paths containing (filterable) text file resources to place in
        this module's jar
    deployjar: An optional boolean that turns on generation of a monolithic deploy jar
    buildflags: A list of additional command line arguments to pass to the underlying build system
        for this target"""

    ExportableJvmLibrary.__init__(self,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes,
                                  buildflags,
                                  is_meta)

    self.java_sources = java_sources

    base_parent = os.path.dirname(self.target_base)
    self.sibling_resources_base = os.path.join(base_parent, 'resources')
    self.resources = self._resolve_paths(self.sibling_resources_base, resources)

    self.deployjar = deployjar

  def _create_template_data(self):
    allsources = []
    if self.sources:
      allsources += list(os.path.join(self.target_base, source) for source in self.sources)
    if self.resources:
      allsources += list(os.path.join(self.sibling_resources_base, res) for res in self.resources)

    return ExportableJvmLibrary._create_template_data(self).extend(
      java_sources = resolve_target_sources(self.java_sources, '.java'),
      resources = self.resources,
      deploy_jar = self.deployjar,
      allsources = allsources,
    )
