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
from twitter.common.python.platforms import Platform
from twitter.pants.base import TargetDefinitionException
from twitter.pants.targets.python_target import PythonTarget


class PythonBinary(PythonTarget):
  def __init__(self,
               name,
               source=None,
               dependencies=None,
               entry_point=None,
               inherit_path=False,
               zip_safe=True,
               repositories=None,
               indices=None,
               ignore_errors=False,
               allow_pypi=False,
               platforms=(),
               interpreters=(Platform.python(),),
               provides=None):
    """
      name: target name

      source: the python source file that becomes this binary's __main__ [optional]
              if none specified, drops into an interpreter by default

      dependencies: a list of other PythonLibrary or Pants targets this binary depends upon

      entry_point: the default entry point for this binary (by default drops
                   into the entry point defined by @source)

      inherit_path: inherit the sys.path of the environment that this binary runs in

      zip_safe: whether or not this binary is safe to run in compacted (zip-file) form

      repositories: a list of repositories to query for dependencies

      indices: a list of indices to use for packages

      allow_pypi: whether or not this binary should be allowed to hit pypi for dependency
                  management

      platforms: extra platforms to target when building this binary.

      interpreters: the interpreter versions to target when building this binary.  by default the
                    current interpreter version (specify in the form: '2.6', '2.7', '3.2' etc.)
    """
    if source is None and dependencies is None:
      raise TargetDefinitionException(
          'ERROR: no source or dependencies declared for target %s' % name)
    if source and entry_point:
      raise TargetDefinitionException(
          'Can only declare an entry_point if no source binary is specified.')
    if not isinstance(platforms, (list, tuple)) and not isinstance(platforms, Compatibility.string):
      raise TargetDefinitionException('platforms must be a list, tuple or string.')
    if not isinstance(interpreters, (list, tuple)):
      raise TargetDefinitionException('interpreters must be a list or tuple.')

    self._entry_point = entry_point
    self._inherit_path = bool(inherit_path)
    self._zip_safe = bool(zip_safe)
    self._interpreters = interpreters
    self._repositories = repositories or []
    self._indices = indices or []
    self._allow_pypi = bool(allow_pypi)
    self._ignore_errors = bool(ignore_errors)

    if isinstance(platforms, Compatibility.string):
      self._platforms = [platforms]
    else:
      self._platforms = platforms
    self._platforms = tuple(self._platforms)

    PythonTarget.__init__(self, name, [] if source is None else [source],
                          dependencies=dependencies,
                          provides=provides)

  @property
  def platforms(self):
    return self._platforms
