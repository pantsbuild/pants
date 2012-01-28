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
from jar_dependency import JarDependency
from pants_target import Pants

class JavaThriftLibrary(ExportableJvmLibrary):
  """Defines a target that builds java stubs from a thrift IDL file."""

  def __init__(self,
               name,
               sources,
               provides = None,
               dependencies = None,
               excludes = None,
               buildflags = None,
               is_meta = False):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the thrift source files this module's jar is compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
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
    self.is_codegen = True

  def _as_jar_dependency(self):
    return ExportableJvmLibrary._as_jar_dependency(self).withSources()

  def _create_template_data(self):
    allsources = []
    if self.sources:
      allsources += list(os.path.join(self.target_base, src) for src in self.sources)

    return ExportableJvmLibrary._create_template_data(self).extend(
      allsources = allsources,
    )
