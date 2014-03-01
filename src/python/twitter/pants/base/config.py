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

try:
  import ConfigParser
except ImportError:
  import configparser as ConfigParser

import os
import getpass

from twitter.pants.base.build_environment import get_buildroot


class Config(object):
  """
    Encapsulates ini-style config file loading and access additionally supporting recursive variable
    substitution using standard python format strings, ie: %(var_name)s will be replaced with the
    value of var_name.
  """

  DEFAULT_SECTION = ConfigParser.DEFAULTSECT

  class ConfigError(Exception):
    pass

  @staticmethod
  def load(configpath=os.path.join(get_buildroot(), 'pants.ini'), defaults=None):
    """
      Loads a Config from the given path, by default the path to the pants.ini file in the current
      build root directory.  Any defaults supplied will act as if specified in the loaded config
      file's DEFAULT section.  The 'buildroot', invoking 'user' and invoking user's 'homedir' are
      automatically defaulted.
    """
    parser = Config.create_parser(defaults)
    with open(configpath) as ini:
      parser.readfp(ini)
    return Config(parser)

  @staticmethod
  def create_parser(defaults=None):
    """
      Creates a config parser that supports %([key-name])s value substitution.  Any defaults
      supplied will act as if specified in the loaded config file's DEFAULT section and be available
      for substitutions.  The 'buildroot', invoking 'user' and invoking user's 'homedir' are
      automatically defaulted.
    """
    standard_defaults = dict(
      buildroot=get_buildroot(),
      homedir=os.path.expanduser('~'),
      user=getpass.getuser(),
      pants_workdir=os.path.join(get_buildroot(), '.pants.d'),
      pants_supportdir=os.path.join(get_buildroot(), 'build-support'),
      pants_distdir=os.path.join(get_buildroot(), 'dist')
    )
    if defaults:
      standard_defaults.update(defaults)
    return ConfigParser.SafeConfigParser(standard_defaults)

  def __init__(self, configparser):
    self.configparser = configparser

    # Overrides
    #
    # This feature allows a second configuration file which will override
    # pants.ini to be specified.  The file is currently specified via an env
    # variable because the cmd line flags are parsed after config is loaded.
    #
    # The main use of the extra file is to have different settings based on
    # the environment.  For example, the setting used to compile or locations
    # of caches might be different between a developer's local environment
    # and the environment used to build and publish artifacts (e.g. Jenkins)
    #
    # The files cannot reference each other's values, so make sure each one is
    # internally consistent
    self.overrides_path = os.environ.get('PANTS_CONFIG_OVERRIDE')
    self.overrides_parser = None
    if self.overrides_path is not None:
      self.overrides_path = os.path.join(get_buildroot(), self.overrides_path)
      self.overrides_parser = Config.create_parser()
      with open(self.overrides_path) as o_ini:
        self.overrides_parser.readfp(o_ini, filename=self.overrides_path)

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
    return self.get(Config.DEFAULT_SECTION, option, type, default=default)

  def get(self, section, option, type=str, default=None):
    """
      Retrieves option from the specified section if it exists and attempts to parse it as type.
      If the specified section is missing a definition for the option, the value is looked up in the
      DEFAULT section.  If there is still no definition found, the default value supplied is
      returned.
    """
    return self._getinstance(section, option, type, default=default)

  def get_required(self, section, option, type=str):
    """Retrieves option from the specified section and attempts to parse it as type.
    If the specified section is missing a definition for the option, the value is
    looked up in the DEFAULT section. If there is still no definition found,
    a `ConfigError` is raised.

    :param string section: Section to lookup the option in, before looking in DEFAULT.
    :param string option: Option to retrieve.
    :param type: Type to retrieve the option as.
    :returns: The option as the specified type.
    :raises: :class:`twitter.pants.base.config.Config.ConfigError` if option is not found.
    """
    val = self.get(section, option, type=type)
    if val is None:
      raise Config.ConfigError('Required option %s.%s is not defined.' % (section, option))
    return val

  def has_section(self, section):
    """Return whether or not this config has the section."""
    return self.configparser.has_section(section)

  def _has_option(self, section, option):
    if self.overrides_parser and self.overrides_parser.has_option(section, option):
      return True
    elif self.configparser.has_option(section, option):
      return True
    return False

  def _get_value(self, section, option):
    if self.overrides_parser and self.overrides_parser.has_option(section, option):
      return self.overrides_parser.get(section, option)
    return self.configparser.get(section, option)

  def _getinstance(self, section, option, type, default=None):
    if not self._has_option(section, option):
      return default
    raw_value = self._get_value(section, option)
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
