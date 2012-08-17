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

 # TODO(Anand) Remove this from pants proper when a code adjoinment mechanism exists
 # or ok if/when thriftstore is open sourced as well..
class JavaThriftstoreDMLLibrary(ExportableJvmLibrary):
  """Defines a target that builds java stubs from a thriftstore DDL file."""

  def __init__(self,
               name,
               sources,
               dependencies = None):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the thriftstore source files this module's jar is compiled from
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    """

    ExportableJvmLibrary.__init__(self,
                                  name,
                                  sources,
                                  provides = None,
                                  dependencies = dependencies)
    self.is_codegen = True

  def _as_jar_dependency(self):
    return ExportableJvmLibrary._as_jar_dependency(self).with_sources()

  def _create_template_data(self):
    allsources = []
    if self.sources:
      allsources += list(os.path.join(self.target_base, src) for src in self.sources)

    return ExportableJvmLibrary._create_template_data(self).extend(
      allsources = allsources,
    )
