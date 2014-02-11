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

from twitter.pants.base import manual

from .internal import InternalTarget
from .with_sources import TargetWithSources


@manual.builddict(tags=['jvm'])
class Resources(InternalTarget, TargetWithSources):
  """Describes a set of resource files to be embedded in a library or binary.

  If your target compiles to the JVM (e.g., ``java_library``,
  ``scala_library``, ``junit_tests``), you might have files
  that you need to access as resources. Each of these targets has an optional
  argument called ``resources`` that expects a list of target addresses that
  resolve to targets whose type is resource.

  In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
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
