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

from twitter.pants.base import TargetDefinitionException

from internal import InternalTarget
from jar_dependency import JarDependency
from with_sources import TargetWithSources

class JvmTarget(InternalTarget, TargetWithSources):
  """A base class for all java module targets that provides path and dependency translation."""

  def __init__(self, target_base, name, sources, dependencies, excludes = None,
               buildflags = None, is_meta = False):
    InternalTarget.__init__(self, name, dependencies, is_meta)
    TargetWithSources.__init__(self, target_base, name, is_meta)

    if sources is None or sources == []:
      raise TargetDefinitionException(self, 'No sources specified')

    self.sources = self._resolve_paths(self.target_base, sources)
    self.excludes = excludes
    self.buildflags = buildflags

    custom_antxml = '%s.xml' % self.name
    buildfile = self.address.buildfile.full_path
    custom_antxml_path = os.path.join(os.path.dirname(buildfile), custom_antxml)
    self.custom_antxml_path = custom_antxml_path if os.path.exists(custom_antxml_path) else None

  def _as_jar_dependency(self):
    jar_dependency, _, _ = self._get_artifact_info()
    jar = JarDependency(org = jar_dependency.org, name = jar_dependency.name, rev = None)
    jar._id = self._id
    return jar

  def _as_jar_dependencies(self):
    yield self._as_jar_dependency()

  def _get_artifact_info(self):
    provides = self._provides()
    exported = bool(provides)

    org = provides.org if exported else 'internal'
    module = provides.name if exported else self._id
    version = provides.rev if exported else None

    id = "%s-%s" % (provides.org, provides.name) if exported else self._id

    return JarDependency(org = org, name = module, rev = version), id, exported

  def _provides(self):
    return None
