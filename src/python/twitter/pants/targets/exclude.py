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

from twitter.pants.base.generator import TemplateData

class Exclude(object):
  """Represents a dependency exclude pattern to filter transitive dependencies against."""

  def __init__(self, org, name = None):
    self.org = org
    self.name = name

  def __eq__(self, other):
    return other and (
      type(other) == Exclude) and (
      self.org == other.org) and (
      self.name == other.name)

  def __hash__(self):
    value = 17
    value *= 37 + hash(self.org)
    value *= 37 + hash(self.name)
    return value

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "org=%s name=%s" % (self.org, self.name)

  def _create_template_data(self):
    return TemplateData(
      org = self.org,
      name = self.name,
    )
