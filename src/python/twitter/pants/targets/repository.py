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

from twitter.pants.base import manual, Target


@manual.builddict(tags=["jvm"])
class Repository(Target):
  """An artifact repository, such as a maven repo."""

  def __init__(self, name, url, push_db, exclusives=None):
    """
    :param string name: Name of the repository.
    :param string url: Optional URL of the repository.
    :param string push_db: Path of the push history file.
    """

    super(Repository, self).__init__(name, exclusives=exclusives)

    self.name = name
    self.url = url
    self.push_db = push_db

  def __eq__(self, other):
    result = other and (
      type(other) == Repository) and (
      self.name == other.name)
    return result

  def __hash__(self):
    return hash(self.name)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s -> %s (%s)" % (self.name, self.url, self.push_db)
