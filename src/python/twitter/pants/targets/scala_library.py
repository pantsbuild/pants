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

from twitter.common.collections import maybe_list

from twitter.pants.base import Target

from .exportable_jvm_library import ExportableJvmLibrary
from .resources import WithLegacyResources

from . import JavaLibrary


class ScalaLibrary(ExportableJvmLibrary, WithLegacyResources):
  """Defines the source code and dependencies of a scala library."""

  def __init__(self, name, sources=None, java_sources=None, provides=None, dependencies=None,
               excludes=None, resources=None, deployjar=False, buildflags=None):

    """name:      The name of this target, addressable via pants via the portion of the address spec
                  following the colon.
    sources:      A list of paths containing the scala source files this scala library is composed
                  of.
    java_sources: An optional JavaLibrary target or list of targets containing the java libraries
                  this library has a circular dependency on.  Prefer using dependencies to express
                  non-circular dependencies.
    provides:     An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of local and remote dependencies of this library.
    excludes:     An optional list of dependency Exclude objects to filter all of this module's
                  transitive dependencies against.
    resources:    An optional list of paths (DEPRECATED) or Resource targets containing resources
                  that belong on this library's classpath.
    deployjar:    DEPRECATED - An optional boolean that turns on generation of a monolithic deploy
                  jar - now ignored.
    buildflags:   DEPRECATED - A list of additional command line arguments to pass to the underlying
                  build system for this target - now ignored.
    """

    ExportableJvmLibrary.__init__(self, name, sources, provides, dependencies, excludes)
    WithLegacyResources.__init__(self, name, sources=sources, resources=resources)

    self.add_labels('scala')

    # Defer resolves until done parsing the current BUILD file, certain source_root arrangements
    # might allow java and scala sources to co-mingle and so have targets in the same BUILD.
    self._post_construct(self._link_java_cycles, java_sources)

  def _link_java_cycles(self, java_sources):
    if java_sources:
      self.java_sources = list(Target.resolve_all(maybe_list(java_sources, Target), JavaLibrary))
    else:
      self.java_sources = []

    # We have circular java/scala dep, add an inbound dependency edge from java to scala in this
    # case to force scala compilation to precede java - since scalac supports generating java stubs
    # for these cycles and javac does not this is both necessary and always correct.
    for java_target in self.java_sources:
      java_target.update_dependencies([self])
