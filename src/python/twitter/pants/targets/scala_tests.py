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

from twitter.pants.base import manual

from .jvm_target import JvmTarget
from .resources import Resources


@manual.builddict(tags=['scala'])
class ScalaTests(JvmTarget):
  """Tests a Scala library."""

  def __init__(self,
               name,
               sources=None,
               java_sources=None,
               dependencies=None,
               excludes=None,
               resources=None,
               exclusives=None):

    """
    :param name: The name of this module target, addressable via pants via the portion of the spec
      following the colon
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param java_sources:
      :class:`twitter.pants.targets.java_library.JavaLibrary` or list of
      JavaLibrary targets this library has a circular dependency on.
      Prefer using dependencies to express non-circular dependencies.
    :param Artifact provides:
      The :class:`twitter.pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param resources: An optional list of Resources that should be in this target's classpath.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """

    super(ScalaTests, self).__init__(name, sources, dependencies, excludes, exclusives=exclusives)

    # TODO(John Sirois): Merge handling with ScalaLibrary.java_sources - which is different and
    # likely more correct.
    self.java_sources = java_sources

    self.resources = list(self.resolve_all(resources, Resources))
    self.add_labels('scala', 'tests')
