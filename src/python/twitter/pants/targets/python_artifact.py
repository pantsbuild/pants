# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

from .python_target import PythonTarget


class PythonArtifact(object):
  """Represents a Python setup.py-based project."""
  class MissingArgument(Exception): pass
  class UnsupportedArgument(Exception): pass

  UNSUPPORTED_ARGS = frozenset([
    'data_files',
    'package_dir',
    'package_data',
    'packages',
  ])

  def __init__(self, **kwargs):
    self._kw = kwargs
    self._library = None

    def has(name):
      value = self._kw.get(name)
      if value is None:
        raise self.MissingArgument('PythonArtifact requires %s to be specified!' % name)
      return value

    def misses(name):
      if name in self._kw:
        raise self.UnsupportedArgument('PythonArtifact prohibits %s from being specified' % name)

    self._version = has('version')
    self._name = has('name')
    for arg in self.UNSUPPORTED_ARGS:
      misses(arg)

  @property
  def library(self):
    return self._library

  @library.setter
  def library(self, value):
    assert isinstance(value, PythonTarget)
    self._library = value

  @property
  def key(self):
    return '%s==%s' % (self._name, self._version)
