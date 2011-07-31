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

from exportable_jvm_library import ExportableJvmLibrary

class JavaLibrary(ExportableJvmLibrary):
  """Defines a target that produces a java library."""

  @classmethod
  def _aggregate(cls, name, provides, deployjar, buildflags, java_libs, target_base):
    all_deps = OrderedSet()
    all_excludes = OrderedSet()
    all_sources = []
    all_resources = []
    all_binary_resources = []

    for java_lib in java_libs:
      if java_lib.resolved_dependencies:
        all_deps.update(dep for dep in java_lib.jar_dependencies if dep.rev is not None)
      if java_lib.excludes:
        all_excludes.update(java_lib.excludes)
      if java_lib.sources:
        all_sources.extend(java_lib.sources)
      if java_lib.resources:
        all_resources.extend(java_lib.resources)
      if java_lib.binary_resources:
        all_binary_resources.extend(java_lib.binary_resources)

    return JavaLibrary(name,
                       all_sources,
                       target_base = target_base,
                       provides = provides,
                       dependencies = all_deps,
                       excludes = all_excludes,
                       resources = all_resources,
                       binary_resources = all_binary_resources,
                       deployjar = deployjar,
                       buildflags = buildflags,
                       is_meta = True)

  def __init__(self, name, sources,
               target_base = None,
               provides = None,
               dependencies = None,
               excludes = None,
               resources = None,
               binary_resources = None,
               deployjar = False,
               buildflags = None,
               is_meta = False):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the java source files this modules jar is compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    resources: An optional list of paths containing (filterable) text file resources to place in
        this module's jar
    binary_resources: An optional list of paths containing binary resources to place in this
        module's jar
    deployjar: An optional boolean that turns on generation of a monolithic deploy jar
    buildflags: A list of additional command line arguments to pass to the underlying build system
        for this target"""

    ExportableJvmLibrary.__init__(self,
                                  target_base,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes,
                                  buildflags,
                                  is_meta)

    self.sibling_resources_base = os.path.join(os.path.dirname(self.target_base), 'resources')
    self.resources = self._resolve_paths(self.sibling_resources_base, resources)
    self.binary_resources = self._resolve_paths(self.sibling_resources_base, binary_resources)
    self.deployjar = deployjar

  def _create_template_data(self):
    allsources = []
    if self.sources:
      allsources += list(os.path.join(self.target_base, source) for source in self.sources)
    if self.resources:
      allsources += list(os.path.join(self.sibling_resources_base, res) for res in self.resources)
    if self.binary_resources:
      allsources += list(os.path.join(self.sibling_resources_base, res)
                         for res in self.binary_resources)

    return ExportableJvmLibrary._create_template_data(self).extend(
      resources = self.resources,
      binary_resources = self.binary_resources,
      deploy_jar = self.deployjar,
      allsources = allsources,
      processors = []
    )
