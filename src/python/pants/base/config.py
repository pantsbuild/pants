# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import getpass
import itertools
import os

import six

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.util.eval import parse_literal
from pants.util.strutil import is_text_or_binary


try:
  import ConfigParser
except ImportError:
  import configparser as ConfigParser


class Config(object):
  """Encapsulates ini-style config file loading and access.

  Supports recursive variable substitution using standard python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """
  DEFAULT_SECTION = ConfigParser.DEFAULTSECT

  class ConfigError(Exception):
    pass

  @classmethod
  def _munge_configpaths_arg(cls, configpaths):
    """Converts a string or iterable-of-strings argument into a tuple of strings.

    Result is hashable, so may be used as a cache key.
    """
    if is_text_or_binary(configpaths):
      return (configpaths,)
    return tuple(configpaths) if configpaths else (os.path.join(get_buildroot(), 'pants.ini'),)

  @classmethod
  def load(cls, configpaths=None, seed_values=None):
    """Loads config from the given paths.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param configpaths: Load from these paths. Later instances take precedence over earlier ones.
                        If unspecified, loads from pants.ini in the current build root directory.
    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """
    configpaths = cls._munge_configpaths_arg(configpaths)
    single_file_configs = []
    for configpath in configpaths:
      parser = cls.create_parser(seed_values)
      with open(configpath, 'r') as ini:
        parser.readfp(ini)
      single_file_configs.append(SingleFileConfig(configpath, parser))
    return ChainedConfig(single_file_configs)

  @classmethod
  def create_parser(cls, seed_values=None):
    """Creates a config parser that supports %([key-name])s value substitution.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """
    seed_values = seed_values or {}
    buildroot = seed_values.get('buildroot', get_buildroot())

    all_seed_values = {
      'buildroot': buildroot,
      'homedir': os.path.expanduser('~'),
      'user': getpass.getuser(),
      'pants_bootstrapdir': get_pants_cachedir(),
      'pants_configdir': get_pants_configdir(),
    }

    def update_dir_from_seed_values(key, default):
      all_seed_values[key] = seed_values.get(key, os.path.join(buildroot, default))
    update_dir_from_seed_values('pants_workdir', '.pants.d')
    update_dir_from_seed_values('pants_supportdir', 'build-support')
    update_dir_from_seed_values('pants_distdir', 'dist')

    return ConfigParser.SafeConfigParser(all_seed_values)

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

  def getdefault(self, option, type=six.string_types, default=None):
    """Retrieves option from the DEFAULT section if it exists and attempts to parse it as type.

    If there is no definition found, the default value supplied is returned.
    """
    return self.get(Config.DEFAULT_SECTION, option, type, default=default)

  def get(self, section, option, type=six.string_types, default=None):
    """Retrieves option from the specified section (or 'DEFAULT') and attempts to parse it as type.

    If the specified section does not exist or is missing a definition for the option, the value is
    looked up in the DEFAULT section.  If there is still no definition found, the default value
    supplied is returned.
    """
    return self._getinstance(section, option, type, default=default)

  def get_required(self, section, option, type=six.string_types):
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
      raise Config.ConfigError('Required option {}.{} is not defined.'.format(section, option))
    return val

  def _getinstance(self, section, option, type_, default=None):
    if not self.has_option(section, option):
      return default

    raw_value = self.get_value(section, option)
    # We jump through some hoops here to deal with the fact that `six.string_types` is a tuple of
    # types.
    if (type_ == six.string_types or
        (isinstance(type_, type) and issubclass(type_, six.string_types))):
      return raw_value

    key = '{}.{}'.format(section, option)
    return parse_literal(name=key, val=raw_value, acceptable_types=type_,
                         raise_type=self.ConfigError)

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

  def get_source_for_option(self, section, option):
    """Returns the path to the source file the given option was defined in.

    :param string section: the scope of the option.
    :param string option: the name of the option.
    :returns: the path to the config file, or None if the option was not defined by a config file.
    :rtype: string
    """
    raise NotImplementedError


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

  def get_source_for_option(self, section, option):
    if self.has_option(section, option):
      return self.sources()[0]
    return None


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

  def get_source_for_option(self, section, option):
    for cfg in self.configs:
      if cfg.has_option(section, option):
        return cfg.get_source_for_option(section, option)
    return None
