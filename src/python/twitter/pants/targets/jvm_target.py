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

from twitter.common.collections import maybe_list

from .exclude import Exclude
from .internal import InternalTarget
from .jarable import Jarable
from .with_sources import TargetWithSources


class JvmTarget(InternalTarget, TargetWithSources, Jarable):
  """A base class for all java module targets that provides path and dependency translation."""

  def __init__(self,
               name,
               sources,
               dependencies,
               excludes=None,
               configurations=None,
               exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: One or more :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param configurations: One or more ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """
    InternalTarget.__init__(self, name, dependencies, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources)

    self.declared_dependencies = set(dependencies or [])
    self.add_labels('jvm')
    for source in self.sources:
      rel_path = os.path.join(self.target_base, source)
      TargetWithSources.register_source(rel_path, self)
    self.excludes = maybe_list(excludes or [], Exclude)
    self.configurations = maybe_list(configurations or [])

  def _provides(self):
    return None
