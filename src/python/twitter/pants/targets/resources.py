# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

from . import util
from .internal import InternalTarget
from .with_sources import TargetWithSources


@manual.builddict(tags=['jvm'])
class Resources(InternalTarget, TargetWithSources):
  """A set of files accessible as resources from the JVM classpath.

  Looking for loose files in your application bundle? Those are :ref:`bdict_bundle`\ s.

  Resources are Java-style resources accessible via the ``Class.getResource``
  and friends API. In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
  """

  def __init__(self, name, sources, exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the resources
      this library provides.
    """
    # TODO(John Sirois): XXX Review why this is an InternalTarget
    InternalTarget.__init__(self, name, dependencies=None, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources=sources, exclusives=exclusives)

  def has_sources(self, extension=None):
    """``Resources`` never own sources of any particular native type, like for example
    ``JavaLibrary``.
    """
    # TODO(John Sirois): track down the reason for this hack and kill or explain better.
    return extension is None


class WithResources(InternalTarget):
  """A mixin for internal targets that have resources."""

  def __init__(self, *args, **kwargs):
    super(WithResources, self).__init__(*args, **kwargs)
    self._resources = []
    self._raw_resources = None

  @property
  def resources(self):
    if self._raw_resources is not None:
      self._resources = list(self.resolve_all(self._raw_resources, Resources))
      self.update_dependencies(self._resources)
      self._raw_resources = None
    return self._resources

  @resources.setter
  def resources(self, resources):
    self._resources = []
    self._raw_resources = util.resolve(resources)

  def resolve(self):
    # TODO(John Sirois): Clean this up when BUILD parse refactoring is tackled.
    unused_resolved_resources = self.resources

    for resolved in super(WithResources, self).resolve():
      yield resolved
