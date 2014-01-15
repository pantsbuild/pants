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

import os

from twitter.common.collections import maybe_list
from twitter.common.lang import Compatibility
from twitter.common.python.pex_info import PexInfo

from twitter.pants.base import Target, TargetDefinitionException

from .python_target import PythonTarget


class PythonBinary(PythonTarget):
  """Produces a Python binary.

  Python binaries are pex files, self-contained executable shell
  scripts that contain a complete Python environment capable of
  running the target. For more information about pex files see
  https://github.com/twitter/commons/blob/master/src/python/twitter/pants/python/README.md"""

  # TODO(wickman) Consider splitting pex options out into a separate PexInfo builder that can be
  # attached to the binary target.  Ideally the PythonBinary target is agnostic about pex mechanics
  def __init__(self,
               name,
               source=None,
               dependencies=None,
               entry_point=None,
               inherit_path=False,        # pex option
               zip_safe=True,             # pex option
               always_write_cache=False,  # pex option
               repositories=None,         # pex option
               indices=None,              # pex option
               ignore_errors=False,       # pex option
               allow_pypi=False,          # pex option
               platforms=(),
               compatibility=None,
               exclusives=None):
    """
    :param name: target name
    :param source: the python source file that becomes this binary's __main__.
      If None specified, drops into an interpreter by default.
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param entry_point: the default entry point for this binary.  if None, drops into the entry
      point that is defined by source
    :param inherit_path: inherit the sys.path of the environment that this binary runs in
    :param zip_safe: whether or not this binary is safe to run in compacted (zip-file) form
    :param always_write_cache: whether or not the .deps cache of this PEX file should always
      be written to disk.
    :param repositories: a list of repositories to query for dependencies.
    :param indices: a list of indices to use for packages.
    :param platforms: extra platforms to target when building this binary.
    :param compatibility: either a string or list of strings that represents
      interpreter compatibility for this target, using the Requirement-style format,
      e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements agnostic to interpreter class.
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """

    # TODO(John Sirois): Fixup TargetDefinitionException - it has awkward Target base-class
    # initialization requirements right now requiring this Target.__init__.
    Target.__init__(self, name, exclusives=exclusives)

    if source is None and entry_point is None:
      raise TargetDefinitionException(self,
          'A python binary target must specify either source or entry_point.')

    PythonTarget.__init__(self,
        name,
        [] if source is None else [source],
        compatibility=compatibility,
        dependencies=dependencies,
        exclusives=exclusives,
    )

    if not isinstance(platforms, (list, tuple)) and not isinstance(platforms, Compatibility.string):
      raise TargetDefinitionException(self,
          'platforms must be a list, tuple or string.')

    self._entry_point = entry_point
    self._inherit_path = bool(inherit_path)
    self._zip_safe = bool(zip_safe)
    self._always_write_cache = bool(always_write_cache)
    self._repositories = maybe_list(repositories or [])
    self._indices = maybe_list(indices or [])
    self._ignore_errors = bool(ignore_errors)
    self._platforms = tuple(maybe_list(platforms or []))

    if source and entry_point:
      entry_point_module = entry_point.split(':', 1)[0]
      source_entry_point = self._translate_to_entry_point(self.sources[0])
      if entry_point_module != source_entry_point:
        raise TargetDefinitionException(self,
            'Specified both source and entry_point but they do not agree: %s vs %s' % (
            source_entry_point, entry_point_module))

  @property
  def platforms(self):
    return self._platforms

  # TODO(wickman) These should likely be attributes on PythonLibrary targets
  # and not PythonBinary targets, or at the very worst, both.
  @property
  def repositories(self):
    return self._repositories

  @property
  def indices(self):
    return self._indices

  def _translate_to_entry_point(self, source):
    source_base, _ = os.path.splitext(source)
    return source_base.replace(os.path.sep, '.')

  @property
  def entry_point(self):
    if self._entry_point:
      return self._entry_point
    elif self.sources:
      assert len(self.sources) == 1
      return self._translate_to_entry_point(self.sources[0])
    else:
      return None

  @property
  def pexinfo(self):
    info = PexInfo.default()
    for repo in self._repositories:
      info.add_repository(repo)
    for index in self._indices:
      info.add_index(index)
    info.zip_safe = self._zip_safe
    info.always_write_cache = self._always_write_cache
    info.inherit_path = self._inherit_path
    info.entry_point = self.entry_point
    info.ignore_errors = self._ignore_errors
    return info
