# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

from twitter.pants.base.build_manual import manual

from .jvm_target import JvmTarget
from .resources import WithResources


@manual.builddict(tags=["jvm"])
class Benchmark(JvmTarget, WithResources):
  """A caliper benchmark.

  Run it with the ``bench`` goal.
  """

  def __init__(self,
               name,
               sources=None,
               java_sources=None,
               dependencies=None,
               excludes=None,
               resources=None,
               exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param java_sources:
      :class:`twitter.pants.targets.java_library.JavaLibrary` or list of
      JavaLibrary targets this library has a circular dependency on.
      Prefer using dependencies to express non-circular dependencies.
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param resources: An optional list of ``resources`` targets containing text
      file resources to place in this module's jar.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(Benchmark, self).__init__(name, sources, dependencies, excludes, exclusives=exclusives)

    self.java_sources = java_sources
    self.resources = resources
