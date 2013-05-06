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

from twitter.pants.base import manua
l
from .jvm_target import JvmTarget
from .resources import Resources


@manual.builddict(tags=["java"])
class JavaTests(JvmTarget):
  """Tests JVM sources with JUnit."""

  def __init__(self,
               name,
               sources=None,
               dependencies=None,
               excludes=None,
               resources=None,
               buildflags=None,
               exclusives=None):
    """
   :param string name: The name of this target, which combined with this
     build file defines the target :class:`twitter.pants.base.address.Address`.
   :param sources: A list of filenames representing the source code
     this library is compiled from.
   :type sources: list of strings
   :param Artifact provides:
     The :class:`twitter.pants.targets.artifact.Artifact`
     to publish that represents this target outside the repo.
   :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
     this target depends on.
   :type dependencies: list of targets
   :param excludes: List of :class:`twitter.pants.targets.exclude.Exclude` instances
     to filter this target's transitive dependencies against.
   :param resources: An optional list of ``resources`` targets containing text
     file resources to place in this module's jar.
   :param buildflags: Unused, and will be removed in a future release.
   :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
   """

    JvmTarget.__init__(self, name, sources, dependencies, excludes, exclusives=exclusives)
    self.add_labels('java', 'tests')
    self.resources = list(self.resolve_all(resources, Resources))
