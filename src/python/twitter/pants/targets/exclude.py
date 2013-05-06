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


@manual.builddict(tags=["jvm"])
class Exclude(object):
  """Represents a dependency exclude pattern to filter transitive dependencies against."""

  def __init__(self, org, name=None):
    """
    :param string org: Organization of the artifact to filter,
      known as groupId in Maven parlance.
    :param string name: Name of the artifact to filter in the org, or filter
      everything if unspecified.
    """
    self.org = org
    self.name = name

  def __eq__(self, other):
    return all([other,
                type(other) == Exclude,
                self.org == other.org,
                self.name == other.name])

  def __hash__(self):
    return hash((self.org, self.name))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "Exclude(org='%s', name=%s)" % (self.org, ('%s' % self.name) if self.name else None)
