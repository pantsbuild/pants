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

class AnnotationProcessor(ExportableJvmLibrary):
  """Defines a target that produces a java library containing one or more annotation processors."""

  _SRC_DIR = 'src/java'

  @classmethod
  def _aggregate(cls, name, provides, apt_libs):
    all_deps = OrderedSet()
    all_excludes = OrderedSet()
    all_sources = []
    all_resources = []
    all_binary_resources = []
    all_annotation_processors = []

    for apt_lib in apt_libs:
      if apt_lib.resolved_dependencies:
        all_deps.update(dep for dep in apt_lib.jar_dependencies if dep.rev is not None)
      if apt_lib.excludes:
        all_excludes.update(apt_lib.excludes)
      if apt_lib.sources:
        all_sources.extend(apt_lib.sources)
      if apt_lib.resources:
        all_resources.extend(apt_lib.resources)
      if apt_lib.binary_resources:
        all_binary_resources.extend(apt_lib.binary_resources)
      if apt_lib.processors:
        all_annotation_processors.extend(apt_lib.processors)

    return AnnotationProcessor(name,
                               all_sources,
                               provides = provides,
                               dependencies = all_deps,
                               excludes = all_excludes,
                               resources = all_resources,
                               binary_resources = all_binary_resources,
                               processors = all_annotation_processors,
                               is_meta = True)

  def __init__(self, name, sources,
               provides = None,
               dependencies = None,
               excludes = None,
               resources = None,
               binary_resources = None,
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
    binary_resources: An optional list of paths containing binary resources to place in this
        module's jar
    processors: a list of the fully qualified class names of the annotation processors this library
        exports"""

    ExportableJvmLibrary.__init__(self,
                                  AnnotationProcessor._SRC_DIR,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes,
                                  [],
                                  is_meta)

    self.resources = self._resolve_paths(ExportableJvmLibrary.RESOURCES_BASE_DIR, resources)
    self.binary_resources = self._resolve_paths(ExportableJvmLibrary.RESOURCES_BASE_DIR,
                                                binary_resources)
    self.processors = processors

  def _create_template_data(self):
    allsources = []
    if self.sources:
      allsources += [ os.path.join(AnnotationProcessor._SRC_DIR, source)
                      for source in self.sources ]
    if self.resources:
      allsources += [ os.path.join(ExportableJvmLibrary.RESOURCES_BASE_DIR, res)
                      for res in self.resources ]
    if self.binary_resources:
      allsources += [ os.path.join(ExportableJvmLibrary.RESOURCES_BASE_DIR, res)
                      for res in self.binary_resources ]

    return ExportableJvmLibrary._create_template_data(self).extend(
      resources = self.resources,
      binary_resources = self.binary_resources,
      deploy_jar = False,
      allsources = allsources,
      processors = self.processors
    )
