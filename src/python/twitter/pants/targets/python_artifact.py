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

from twitter.pants.base.build_manual import manual

from .python_target import PythonTarget


@manual.builddict(tags=["python"])
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
    self._binaries = {}

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
  def name(self):
    return self._name

  @property
  def version(self):
    return self._version

  @property
  def key(self):
    return '%s==%s' % (self._name, self._version)

  @property
  def setup_py_keywords(self):
    return self._kw

  @property
  def binaries(self):
    return self._binaries

  def with_binaries(self, *args, **kw):
    """Add binaries tagged to this artifact.

    For example: ::

      provides = setup_py(
        name = 'my_library',
        zip_safe = True
      ).with_binaries(
        my_command = pants(':my_library_bin')
      )

    This adds a console_script entry_point for the python_binary target
    pointed at by :my_library_bin.  Currently only supports
    python_binaries that specify entry_point explicitly instead of source.

    Also can take a dictionary, e.g.
    with_binaries({'my-command': pants(...)})
    """
    for arg in args:
      if isinstance(arg, dict):
        self._binaries.update(arg)
    self._binaries.update(kw)
    return self
