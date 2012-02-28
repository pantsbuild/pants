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

from twitter.pants.targets.exportable_jvm_library import ExportableJvmLibrary

class AnnotationProcessor(ExportableJvmLibrary):
  """Defines a target that produces a java library containing one or more annotation processors."""

  def __init__(self, name, sources,
               provides = None,
               dependencies = None,
               excludes = None,
               resources = None,
               processors = None,
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
    processors: a list of the fully qualified class names of the annotation processors this library
        exports"""

    ExportableJvmLibrary.__init__(self,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes,
                                  (),
                                  is_meta)

    self.resources = self._resolve_paths(ExportableJvmLibrary.RESOURCES_BASE_DIR, resources)
    self.processors = processors

  def _create_template_data(self):
    allsources = []
    if self.sources:
      allsources += [ os.path.join(self.target_base, source) for source in self.sources ]
    if self.resources:
      allsources += [ os.path.join(ExportableJvmLibrary.RESOURCES_BASE_DIR, res)
                      for res in self.resources ]

    return ExportableJvmLibrary._create_template_data(self).extend(
      resources = self.resources,
      deploy_jar = False,
      allsources = allsources,
      processors = self.processors
    )
