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

from twitter.pants.base import Target

class Repository(Target):
  """Represents an artifact repository.  Typically this is a maven-style artifact repo."""

  def __init__(self, name, url, push_db, exclusives=None):
    """name: an identifier for the repo
    url: the url used to access the repo and retrieve artifacts or artifact metadata
    push_db: the data file associated with this repo that records artifact push history"""

    Target.__init__(self, name, exclusives=exclusives)

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
