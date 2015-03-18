# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import getpass
import itertools
import os

from six.moves import range

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.util.strutil import is_text_or_binary


try:
  import ConfigParser
except ImportError:
  import configparser as ConfigParser


def reset_default_bootstrap_option_values(defaults, values=None, buildroot=None):
  """Reset the bootstrap options' default values.

  :param defaults: The dict to set the values on.
  :param values: A namespace containing the values to set. If unspecified, uses
                 buildroot-based defaults.
  :param buildroot: If values is None, use this buildroot to generate the hard-coded defaults.
                    If unspecified, uses the detected buildroot.

  The bootstrapping code will use this to set the bootstrapped values. Code that doesn't trigger
  bootstrapping (i.e., the one remaining old-style command) will get the hard-coded defaults, as
  it did before.

  It's a code smell to update nominally static data dynamically, but this is temporary,
  and saves us having to plumb things through to all the Config.from_cache() call sites.

  This method is also called in tests of this code, to reset state for unrelated tests.

  TODO: Remove after all direct config reads have been subsumed into the options system,
        which can pass these into Config.load() itself after bootstrapping them.
  """

  buildroot = buildroot or get_buildroot()
  defaults.update({
    'buildroot': buildroot
  })

  if values:
    defaults.update({
      'pants_workdir': values.pants_workdir,
      'pants_supportdir': values.pants_supportdir,
      'pants_distdir': values.pants_distdir
    })
  else:
    defaults.update({
      'pants_workdir': os.path.join(buildroot, '.pants.d'),
      'pants_supportdir': os.path.join(buildroot, 'build-support'),
      'pants_distdir': os.path.join(buildroot, 'dist')
    })


class Config(object):
  """Encapsulates ini-style config file loading and access.

  Supports recursive variable substitution using standard python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """
  DEFAULT_SECTION = ConfigParser.DEFAULTSECT

  _defaults = {
    'homedir': os.path.expanduser('~'),
    'user': getpass.getuser(),
    'pants_bootstrapdir': get_pants_cachedir(),
    'pants_configdir': get_pants_configdir()
  }
  reset_default_bootstrap_option_values(_defaults)

  class ConfigError(Exception):
    pass

  @classmethod
  def reset_default_bootstrap_option_values(cls, values=None, buildroot=None):
    reset_default_bootstrap_option_values(cls._defaults, values, buildroot)

  _cached_config = None

  @classmethod
  def _munge_configpaths_arg(cls, configpaths):
    """Converts a string or iterable-of-strings argument into a tuple of strings.

    Result is hashable, so may be used as a cache key.
    """
    if is_text_or_binary(configpaths):
      return (configpaths,)
    return tuple(configpaths) if configpaths else (os.path.join(get_buildroot(), 'pants.ini'),)

  @classmethod
  def from_cache(cls):
    if not cls._cached_config:
      raise cls.ConfigError('No config cached.')
    return cls._cached_config

  @classmethod
  def cache(cls, config):
    cls._cached_config = config

  @classmethod
  def load(cls, configpaths=None):
    """Loads config from the given paths.

     By default this is the path to the pants.ini file in the current build root directory.
     Callers may specify a single path, or a list of the paths of configs to be chained, with
     later instances taking precedence over eariler ones.

     Any defaults supplied will act as if specified in the loaded config file's DEFAULT section.
     The 'buildroot', invoking 'user' and invoking user's 'homedir' are automatically defaulted.
    """
    configpaths = cls._munge_configpaths_arg(configpaths)
    single_file_configs = []
    for configpath in configpaths:
      parser = cls.create_parser()
      with open(configpath, 'r') as ini:
        parser.readfp(ini)
      single_file_configs.append(SingleFileConfig(configpath, parser))
    return ChainedConfig(single_file_configs)

  @classmethod
  def create_parser(cls):
    """Creates a config parser that supports %([key-name])s value substitution.

    Any defaults supplied will act as if specified in the loaded config file's DEFAULT section and
    be available for substitutions, along with all the standard defaults defined above.
    """
    return ConfigParser.SafeConfigParser(cls._defaults)

  # TODO(John Sirois): s/type/type_/

  def getbool(self, section, option, default=None):
    """Equivalent to calling get with expected type bool."""
    return self.get(section, option, type=bool, default=default)

  def getint(self, section, option, default=None):
    """Equivalent to calling get with expected type int."""
    return self.get(section, option, type=int, default=default)

  def getfloat(self, section, option, default=None):
    """Equivalent to calling get with expected type float."""
    return self.get(section, option, type=float, default=default)

  def getlist(self, section, option, default=None):
    """Equivalent to calling get with expected type list."""
    return self.get(section, option, type=list, default=default)

  def getdict(self, section, option, default=None):
    """Equivalent to calling get with expected type dict."""
    return self.get(section, option, type=dict, default=default)

  def getdefault(self, option, type=str, default=None):
    """Retrieves option from the DEFAULT section if it exists and attempts to parse it as type.

    If there is no definition found, the default value supplied is returned.
    """
    return self.get(Config.DEFAULT_SECTION, option, type, default=default)

  def get(self, section, option, type=str, default=None):
    """Retrieves option from the specified section (or 'DEFAULT') and attempts to parse it as type.

    If the specified section does not exist or is missing a definition for the option, the value is
    looked up in the DEFAULT section.  If there is still no definition found, the default value
    supplied is returned.
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
    :raises: :class:`pants.base.config.Config.ConfigError` if option is not found.
    """
    val = self.get(section, option, type=type)
    # Empty str catches blank options. If blank entries are ok, use get(..., default='') instead.
    if val is None or val == '':
      raise Config.ConfigError('Required option %s.%s is not defined.' % (section, option))
    return val

  @staticmethod
  def format_raw_value(raw_value):
    lines = raw_value.splitlines()
    for line_number in range(0, len(lines)):
      lines[line_number] = "{line_number:{width}}: {line}".format(
        line_number=line_number + 1,
        line=lines[line_number],
        width=len(str(len(lines))))
    return '\n'.join(lines)

  def _getinstance(self, section, option, type, default=None):
    if not self.has_option(section, option):
      return default
    raw_value = self.get_value(section, option)
    if issubclass(type, str):
      return raw_value

    try:
      parsed_value = eval(raw_value, {}, {})
    except SyntaxError as e:
      raise Config.ConfigError('No valid {type_name} for {section}.{option}:\n{value}\n{error}'
                               .format(type_name=type.__name__,
                                       section=section,
                                       option=option,
                                       value=Config.format_raw_value(raw_value),
                                       error=e))
    if not isinstance(parsed_value, type):
      raise Config.ConfigError('No valid {type_name} for {section}.{option}:\n{value}'
                               .format(type_name=type.__name__,
                                       section=section,
                                       option=option,
                                       value=Config.format_raw_value(raw_value)))

    return parsed_value

  # Subclasses must implement.

  def sources(self):
    """Return the sources of this config as a list of filenames."""
    raise NotImplementedError()

  def has_section(self, section):
    """Return whether this config has the section."""
    raise NotImplementedError()

  def has_option(self, section, option):
    """Return whether this config specified a value the option."""
    raise NotImplementedError()

  def get_value(self, section, option):
    """Return the value of the option in this config, as a string, or None if no value specified."""
    raise NotImplementedError()


class SingleFileConfig(Config):
  """Config read from a single file."""
  def __init__(self, configpath, configparser):
    super(SingleFileConfig, self).__init__()
    self.configpath = configpath
    self.configparser = configparser

  def sources(self):
    return [self.configpath]

  def has_section(self, section):
    return self.configparser.has_section(section)

  def has_option(self, section, option):
    return (self.configparser.has_option(section, option) or
            self.configparser.has_option(self.DEFAULT_SECTION, option))

  def get_value(self, section, option):
    if self.configparser.has_option(section, option):
      return self.configparser.get(section, option)
    else:
      return self.configparser.get(self.DEFAULT_SECTION, option)


class ChainedConfig(Config):
  """Config read from multiple sources."""
  def __init__(self, configs):
    """
    :param configs: A list of Config instances to chain.
                    Later instances take precedence over earlier ones.
    """
    super(ChainedConfig, self).__init__()
    self.configs = list(reversed(configs))

  def sources(self):
    return list(itertools.chain.from_iterable(cfg.sources() for cfg in self.configs))

  def has_section(self, section):
    for cfg in self.configs:
      if cfg.has_section(section):
        return True
    return False

  def has_option(self, section, option):
    for cfg in self.configs:
      if cfg.has_option(section, option):
        return True
    return False

  def get_value(self, section, option):
    for cfg in self.configs:
      try:
        return cfg.get_value(section, option)
      except (ConfigParser.NoSectionError, ConfigParser.NoOptionError):
        pass
    if not self.has_section(section):
      raise ConfigParser.NoSectionError(section)
    raise ConfigParser.NoOptionError(option, section)
