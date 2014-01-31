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

from twitter.common.lang import Compatibility

from twitter.pants.base.build_manual import manual

from .pants_target import Pants
from .repository import Repository
from .util import resolve


@manual.builddict(tags=["jvm"])
class Artifact(object):
  """Represents a jvm artifact ala maven or ivy.

  Used in the ``provides`` parameter to *jvm*\_library targets.
  """

  def __init__(self, org, name, repo, description=None):
    """
    :param string org: Organization of this artifact, or groupId in maven parlance.
    :param string name: Name of the artifact, or artifactId in maven parlance.
    :param repo: :class:`twitter.pants.targets.repository.Repository`
      this artifact is published to.
    :param string description: Description of this artifact.
    """
    if not isinstance(org, Compatibility.string):
      raise ValueError("org must be %s but was %s" % (Compatibility.string, org))
    if not isinstance(name, Compatibility.string):
      raise ValueError("name must be %s but was %s" % (Compatibility.string, name))

    if repo is None:
      raise ValueError("repo must be supplied")
    repos = []
    for tgt in maybe_list(resolve(repo), expected_type=(Pants, Repository)):
      repos.append(tgt.resolve())
    if len(repos) != 1:
      raise ValueError("An artifact must have exactly 1 repo, given: %s" % repos)
    repo = repos[0]

    if description is not None and not isinstance(description, Compatibility.string):
      raise ValueError("description must be None or %s but was %s"
                       % (Compatibility.string, description))

    self.org = org
    self.name = name
    self.rev = None
    self.repo = repo
    self.description = description

  def __eq__(self, other):
    result = other and (
      type(other) == Artifact) and (
      self.org == other.org) and (
      self.name == other.name)
    return result

  def __hash__(self):
    return hash((self.org, self.name))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s-%s -> %s" % (self.org, self.name, self.repo)
