# ==================================================================================================
# Copyright 2014 Twitter, Inc.
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


class PythonSetup(object):
  """A clearing house for configuration data needed by components setting up python environments."""

  def __init__(self, config, section='python-setup'):
    self._config = config
    self._section = section

  @property
  def scratch_root(self):
    """Returns the root scratch space for assembling python environments.

    Components should probably carve out their own directory rooted here.  See `scratch_dir`.
    """
    return self._config.get(
        self._section,
        'cache_root',
        default=os.path.join(self._config.getdefault('pants_workdir'), 'python'))

  def scratch_dir(self, key, default_name=None):
    """Returns a named scratch dir.

    By default this will be a child of the `scratch_root` with the same name as the key.

    :param string key: The pants.ini config key this scratch dir can be overridden with.
    :param default_name: A name to use instead of the keyname for the scratch dir.

    User's can override the location using the key in pants.ini.
    """
    return self._config.get(
        self._section,
        key,
        default=os.path.join(self.scratch_root, default_name or key))
