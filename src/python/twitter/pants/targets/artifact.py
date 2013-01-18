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
from twitter.pants.targets.util import resolve

class Artifact(object):
  """Represents a jvm artifact ala maven or ivy."""

  def __init__(self, org, name, repo, description=None):
    """
      :org the originization of this artifact, the group id in maven parlance
      :name the name of the artifact
      :repo the repository this artifact is published to
      :description a description of this artifact
    """

    self.org = org
    self.name = name
    self.rev = None
    repos = list(resolve(repo).resolve())
    if len(repos) != 1:
      raise Exception("An artifact must have exactly 1 repo, given: %s" % repos)
    self.repo = repos[0]
    self.description = description

  def __eq__(self, other):
    result = other and (
      type(other) == Artifact) and (
      self.org == other.org) and (
      self.name == other.name)
    return result

  def __hash__(self):
    value = 17
    value *= 37 + hash(self.org)
    value *= 37 + hash(self.name)
    return value

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s-%s -> %s" % (self.org, self.name, self.repo)

  def _create_template_data(self):
    return TemplateData(
      org=self.org,
      module=self.name,
      version=self.rev,
      repo=self.repo.name,
      description=self.description
    )

