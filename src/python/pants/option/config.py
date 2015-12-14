# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import getpass
import itertools
import os

import six
from six.moves import configparser
from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.util.eval import parse_expression
from pants.util.strutil import is_text_or_binary


class Config(object):
  """Encapsulates ini-style config file loading and access.

  Supports recursive variable substitution using standard python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """
  _DEFAULT_SECTION = configparser.DEFAULTSECT

  class ConfigError(Exception):
    pass

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
      parser = cls._create_parser(seed_values)
      with open(configpath, 'r') as ini:
        parser.readfp(ini)
      single_file_configs.append(_SingleFileConfig(configpath, parser))
    return _ChainedConfig(single_file_configs)

  @classmethod
  def _munge_configpaths_arg(cls, configpaths):
    """Converts a string or iterable-of-strings argument into a tuple of strings.

    Result is hashable, so may be used as a cache key.
    """
    if is_text_or_binary(configpaths):
      return (configpaths,)
    return tuple(configpaths) if configpaths else (os.path.join(get_buildroot(), 'pants.ini'),)

  @classmethod
  def _create_parser(cls, seed_values=None):
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

    return configparser.SafeConfigParser(all_seed_values)

  def get(self, section, option, type_=six.string_types, default=None):
    """Retrieves option from the specified section (or 'DEFAULT') and attempts to parse it as type.

    If the specified section does not exist or is missing a definition for the option, the value is
    looked up in the DEFAULT section.  If there is still no definition found, the default value
    supplied is returned.
    """
    return self._getinstance(section, option, type_, default)

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
    return parse_expression(name=key, val=raw_value, acceptable_types=type_,
                            raise_type=self.ConfigError)

  # Subclasses must implement.
  def sources(self):
    """Returns the sources of this config as a list of filenames."""
    raise NotImplementedError()

  def sections(self):
    """Returns the sections in this config (not including DEFAULT)."""
    raise NotImplementedError()

  def has_section(self, section):
    """Returns whether this config has the section."""
    raise NotImplementedError()

  def has_option(self, section, option):
    """Returns whether this config specified a value the option."""
    raise NotImplementedError()

  def get_value(self, section, option):
    """Returns the value of the option in this config as a string, or None if no value specified."""
    raise NotImplementedError()

  def get_source_for_option(self, section, option):
    """Returns the path to the source file the given option was defined in.

    :param string section: the scope of the option.
    :param string option: the name of the option.
    :returns: the path to the config file, or None if the option was not defined by a config file.
    :rtype: string
    """
    raise NotImplementedError


class _SingleFileConfig(Config):
  """Config read from a single file."""

  def __init__(self, configpath, configparser):
    super(_SingleFileConfig, self).__init__()
    self.configpath = configpath
    self.configparser = configparser

  def sources(self):
    return [self.configpath]

  def sections(self):
    return self.configparser.sections()

  def has_section(self, section):
    return self.configparser.has_section(section)

  def has_option(self, section, option):
    return (self.configparser.has_option(section, option) or
            self.configparser.has_option(self._DEFAULT_SECTION, option))

  def get_value(self, section, option):
    if self.configparser.has_option(section, option):
      return self.configparser.get(section, option)
    else:
      return self.configparser.get(self._DEFAULT_SECTION, option)

  def get_source_for_option(self, section, option):
    if self.has_option(section, option):
      return self.sources()[0]
    return None


class _ChainedConfig(Config):
  """Config read from multiple sources."""

  def __init__(self, configs):
    """
    :param configs: A list of Config instances to chain.
                    Later instances take precedence over earlier ones.
    """
    super(_ChainedConfig, self).__init__()
    self.configs = list(reversed(configs))

  def sources(self):
    return list(itertools.chain.from_iterable(cfg.sources() for cfg in self.configs))

  def sections(self):
    ret = OrderedSet()
    for cfg in self.configs:
      ret.update(cfg.sections())
    return ret

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
      except (configparser.NoSectionError, configparser.NoOptionError):
        pass
    if not self.has_section(section):
      raise configparser.NoSectionError(section)
    raise configparser.NoOptionError(option, section)

  def get_source_for_option(self, section, option):
    for cfg in self.configs:
      if cfg.has_option(section, option):
        return cfg.get_source_for_option(section, option)
    return None
