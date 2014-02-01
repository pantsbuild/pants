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


from twitter.pants.base import Target, TargetDefinitionException
from .internal import InternalTarget
from .pants_target import Pants
from .with_sources import TargetWithSources

class Wiki(Target):
  """A target that identifies a wiki where pages can be published"""

  def __init__(self, name, url_builder, exclusives=None):
    """:url_builder a function that accepts a page target and an optional wiki :config dict and
    returns a tuple of (alias, fully qualified url)."""
    Target.__init__(self, name, exclusives=exclusives)
    self.url_builder = url_builder


class Page(InternalTarget, TargetWithSources):
  """A target that identifies a single documentation page."""
  def __init__(self, name, source, dependencies=None, resources=None, exclusives=None):
    InternalTarget.__init__(self, name, dependencies, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources=[source], exclusives=exclusives)

    self.resources = self._resolve_paths(resources) if resources else []
    self._wikis = {}

  @property
  def source(self):
    return self.sources[0]

  def register_wiki(self, wiki, **kwargs):
    """Adds this page to the given wiki for publishing.  Wiki-specific configuration is passed as
    kwargs.
    """
    if isinstance(wiki, Pants):
      wiki = wiki.get()
    if not isinstance(wiki, Wiki):
      raise ValueError('The 1st argument must be a wiki target, given: %s' % wiki)
    self._wikis[wiki] = kwargs
    return self

  def wiki_config(self, wiki):
    """Gets the wiki specific config for the given wiki if present or else returns None."""
    return self._wikis.get(wiki)

  def wikis(self):
    """Returns all the wikis registered with this page."""
    return self._wikis.keys()
