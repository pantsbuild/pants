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

from abc import abstractproperty

from twitter.common.lang import AbstractClass

from .jar_dependency import JarDependency


class Jarable(AbstractClass):
  """A mixin that identifies a target as one that can provide a jar."""

  @abstractproperty
  def identifier(self):
    """Subclasses should return a stable unique identifier for the jarable target."""

  @property
  def provides(self):
    """Returns an optional :class:`twitter.pants.targets.Artifact` if this target is exportable.

    Subclasses should override to provide an artifact descriptor when one applies, by default None
    is supplied.
    """
    return None

  def get_artifact_info(self):
    """Returns a triple composed of a :class:`twitter.pants.targets.jar_dependency.JarDependency`
    describing the jar for this target, this target's artifact identifier and a bool indicating if
    this target is exportable.
    """
    exported = bool(self.provides)

    org = self.provides.org if exported else 'internal'
    module = self.provides.name if exported else self.identifier

    id_ = "%s-%s" % (self.provides.org, self.provides.name) if exported else self.identifier

    # TODO(John Sirois): This should return something less than a JarDependency encapsulating just
    # the org and name.  Perhaps a JarFamily?
    return JarDependency(org=org, name=module, rev=None), id_, exported
