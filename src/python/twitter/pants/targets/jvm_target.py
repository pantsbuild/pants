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

from .internal import InternalTarget
from .jar_dependency import JarDependency
from .with_sources import TargetWithSources


class JvmTarget(InternalTarget, TargetWithSources):
  """A base class for all java module targets that provides path and dependency translation."""

  def __init__(self, name, sources, dependencies, excludes=None, configurations=None,
               exclusives=None):
    InternalTarget.__init__(self, name, dependencies, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources)

    self.declared_dependencies = set(dependencies or [])
    self.add_labels('jvm')
    for source in self.sources:
      rel_path = os.path.join(self.target_base, source)
      TargetWithSources.register_source(rel_path, self)
    self.excludes = excludes or []
    self.configurations = configurations

  def _as_jar_dependency(self):
    jar_dependency, _, _ = self._get_artifact_info()
    jar = JarDependency(org=jar_dependency.org, name=jar_dependency.name, rev=None,
                              exclusives=self.declared_exclusives)
    jar.id = self.id
    return jar

  def _as_jar_dependencies(self):
    yield self._as_jar_dependency()


  def _get_artifact_info(self):
    provides = self._provides()
    exported = bool(provides)

    org = provides.org if exported else 'internal'
    module = provides.name if exported else self.id
    version = provides.rev if exported else None

    id = "%s-%s" % (provides.org, provides.name) if exported else self.id

    return JarDependency(org=org, name=module, rev=version), id, exported

  def _provides(self):
    return None
