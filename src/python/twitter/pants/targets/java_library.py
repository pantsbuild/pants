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
# =====================================

from twitter.pants.base import manual, TargetDefinitionException

from .exportable_jvm_library import ExportableJvmLibrary
from .resources import WithLegacyResources


@manual.builddict(tags=["java"])
class JavaLibrary(ExportableJvmLibrary, WithLegacyResources):
  """A collection of Java code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles Java and generates classes. Invoking the ``jar``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  def __init__(self,
               name,
               sources=None,
               provides=None,
               dependencies=None,
               excludes=None,
               resources=None,
               deployjar=False,
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
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    :param deployjar: Unused, and will be removed in a future release.
    :param buildflags: Unused, and will be removed in a future release.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    ExportableJvmLibrary.__init__(self,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes,
                                  exclusives=exclusives)
    WithLegacyResources.__init__(self, name, sources=sources, resources=resources)

    if (sources is None) and (resources is None):
      raise TargetDefinitionException(self, 'Must specify sources and/or resources.')

    self.deployjar = deployjar
    self.add_labels('java')
