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

class ExportableJvmLibrary(JvmTarget):
  """A baseclass for java targets that support being exported to an artifact repository."""
  def __init__(self,
               name,
               sources,
               provides = None,
               dependencies = None,
               excludes = None,
               buildflags = None,
               is_meta = False):

    # it's critical provides is set 1st since _provides() is called elsewhere in the constructor
    # flow
    self.provides = provides

    JvmTarget.__init__(self, name, sources, dependencies, excludes, buildflags, is_meta)
    self.add_label('exportable')

  def _provides(self):
    return self.provides

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
      publish_properties = self.provides.repo.push_db if exported else None,
      publish_repo = self.provides.repo.name if exported else None,
    )
