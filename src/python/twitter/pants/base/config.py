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

__author__ = 'jsirois'

try:
  import ConfigParser
except ImportError:
  import configparser as ConfigParser

import os
import getpass

from twitter.pants import get_buildroot

class Config(object):
  """
    Encapsulates ini-style config file loading and access additionally supporting recursive variable
    substitution using standard python format strings, ie: %(var_name)s will be replaced with the
    value of var_name.
  """

  class ConfigError(Exception): pass

  DEFAULT = 'DEFAULT'

  @staticmethod
  def load(configpath=os.path.join(get_buildroot(), 'pants.ini'), defaults=None):
    """
      Loads a Config from the given path, by default the path to the pants.ini file in the current
      build root directory.  Any defaults supplied will act as if specified in the loaded config
      file's DEFAULT section.  The 'buildroot', invoking 'user' and invoking user's 'homedir' are
      automatically defaulted.
    """
    standard_defaults = dict(
      buildroot=get_buildroot(),
      homedir=os.path.expanduser('~'),
      user=getpass.getuser()
    )
    if defaults:
      standard_defaults.update(defaults)
    return Config(configpath, defaults=standard_defaults)

  def __init__(self, configpath, defaults):
    self.config = ConfigParser.SafeConfigParser(defaults)
    with open(configpath) as ini:
      self.config.readfp(ini, filename=configpath)
    self.file = configpath

  def getbool(self, section, option, default=None):
    """Equivalent to calling get with expected type string"""
    return self.get(section, option, type=bool, default=default)

  def getint(self, section, option, default=None):
    """Equivalent to calling get with expected type int"""
    return self.get(section, option, type=int, default=default)

  def getfloat(self, section, option, default=None):
    """Equivalent to calling get with expected type float"""
    return self.get(section, option, type=float, default=default)

  def getlist(self, section, option, default=None):
    """Equivalent to calling get with expected type list"""
    return self.get(section, option, type=list, default=default)

  def getdict(self, section, option, default=None):
    """Equivalent to calling get with expected type dict"""
    return self.get(section, option, type=dict, default=default)

  def getdefault(self, option, type=str, default=None):
    """
      Retrieves option from the DEFAULT section if it exists and attempts to parse it as type.
      If there is no definition found, the default value supplied is returned.
    """
    return self.get(Config.DEFAULT, option, type, default=default)

  def get(self, section, option, type=str, default=None):
    """
      Retrieves option from the specified section if it exists and attempts to parse it as type.
      If the specified section is missing a definition for the option, the value is looked up in the
      DEFAULT section.  If there is still no definition found, the default value supplied is
      returned.
    """
    return self._getinstance(section, option, type, default=default)

  def _getinstance(self, section, option, type, default=None):
    if not self.config.has_option(section, option):
      return default
    raw_value = self.config.get(section, option)
    if issubclass(type, str):
      return raw_value

    try:
      parsed_value = eval(raw_value, {}, {})
    except SyntaxError as e:
      raise Config.ConfigError('No valid %s for %s.%s: %s\n%s' % (
        type.__name__, section, option, raw_value, e))

    if not isinstance(parsed_value, type):
      raise Config.ConfigError('No valid %s for %s.%s: %s' % (
        type.__name__, section, option, raw_value))

    return parsed_value
