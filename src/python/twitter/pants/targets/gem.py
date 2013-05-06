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

from twitter.common.lang import Compatibility
from twitter.pants.base import manual
from twitter.pants.targets.pants_target import Pants
from twitter.pants.targets.repository import Repository


@manual.builddict(tags=["ruby"])
class Gem(object):
  """Represents a gem to be published.

  Used in the ``provides`` parameter to *ruby*\_library targets."""

  def __init__(self, name, repo):
    """
    :param string name: gem name
    :param repo: :class:`twitter.pants.targets.repository.Repository`
      this artifact is published to.
    """
    if not isinstance(name, Compatibility.string):
      raise ValueError("name must be %s but was %s" % (Compatibility.string, name))
    if not isinstance(repo, (Pants, Repository)):
      raise ValueError("repo must be %s or %s but was %s" % (
        Repository.__name__, Pants.__name__, repo))

    self.name = name
    repos = list(repo.resolve())
    if len(repos) != 1:
      raise ValueError("A gem must have exactly 1 repo, given: %s" % repos)
    self.repo = repos[0]
