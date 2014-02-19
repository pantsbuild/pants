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

from twitter.common.collections import maybe_list

from twitter.pants.base import manual, Target, TargetDefinitionException
from twitter.pants.targets import util

from .exportable_jvm_library import ExportableJvmLibrary
from .resources import WithResources

from . import JavaLibrary


@manual.builddict(tags=['scala'])
class ScalaLibrary(ExportableJvmLibrary, WithResources):
  """A collection of Scala code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles scala and generates classes. Invoking the ``bundle``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  def __init__(self,
               name,
               sources=None,
               java_sources=None,
               provides=None,
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
    :param Artifact provides:
      The :class:`twitter.pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param resources: An optional list of paths (DEPRECATED) or ``resources``
      targets containing resources that belong on this library's classpath.
    :param exclusives: An optional list of exclusives tags.
    """
    super(ScalaLibrary, self).__init__(
        name,
        sources,
        provides,
        dependencies,
        excludes,
        exclusives=exclusives)

    if (sources is None) and (resources is None):
      raise TargetDefinitionException(self, 'Must specify sources and/or resources.')

    self.resources = resources

    self._java_sources = []
    self._raw_java_sources = util.resolve(java_sources)

    self.add_labels('scala')

  @property
  def java_sources(self):
    if self._raw_java_sources is not None:
      self._java_sources = list(Target.resolve_all(maybe_list(self._raw_java_sources, Target),
                                                   JavaLibrary))

      # TODO(John Sirois): reconsider doing this auto-linking.
      # We have circular java/scala dep, add an inbound dependency edge from java to scala in this
      # case to force scala compilation to precede java - since scalac supports generating java stubs
      # for these cycles and javac does not this is both necessary and always correct.
      for java_target in self._java_sources:
        java_target.update_dependencies([self])
    return self._java_sources

