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

from twitter.pants.base.generator import TemplateData
from twitter.pants.targets.jvm_target import JvmTarget

class JavaTests(JvmTarget):
  """Defines a target that tests a java library."""

  def __init__(self,
               name,
               sources = None,
               dependencies = None,
               excludes = None,
               buildflags = None,
               is_meta = False):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the java source files this modules tests are compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    buildflags: A list of additional command line arguments to pass to the underlying build system
        for this target"""

    JvmTarget.__init__(self, name, sources, dependencies, excludes, buildflags, is_meta)

  def _create_template_data(self):
    jar_dependency, id, exported = self._get_artifact_info()

    if self.excludes:
      exclude_template_datas = [exclude._create_template_data() for exclude in self.excludes]
    else:
      exclude_template_datas = None

    return TemplateData(
      id = id,
      name = self.name,
      template_base = self.target_base,
      exported = exported,
      org = jar_dependency.org,
      module = jar_dependency.name,
      version = jar_dependency.rev,
      sources = self.sources,
      dependencies = [dep._create_template_data() for dep in self.jar_dependencies],
      excludes = exclude_template_datas,
      buildflags = self.buildflags,
    )
