# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import getpass
import io
import itertools
import os
from builtins import open
from contextlib import contextmanager
from hashlib import sha1

import six
from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.util.eval import parse_expression
from pants.util.meta import AbstractClass
from pants.util.objects import datatype
from pants.util.py2_compat import configparser


class Config(AbstractClass):
  """Encapsulates ini-style config file loading and access.

  Supports recursive variable substitution using standard python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """
  DEFAULT_SECTION = configparser.DEFAULTSECT

  class ConfigError(Exception):
    pass

  class ConfigValidationError(ConfigError):
    pass

  @classmethod
  def load_file_contents(cls, file_contents, seed_values=None):
    """Loads config from the given string payloads.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param list[FileContents] file_contents: Load from these FileContents. Later instances take
                                             precedence over earlier ones. If empty, returns an
                                             empty config.
    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """

    @contextmanager
    def opener(file_content):
      with io.BytesIO(file_content.content) as fh:
        yield fh

    return cls._meta_load(opener, file_contents, seed_values)

  @classmethod
  def load(cls, config_paths, seed_values=None):
    """Loads config from the given paths.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param list config_paths: Load from these paths. Later instances take precedence over earlier
                              ones. If empty, returns an empty config.
    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """

    @contextmanager
    def opener(f):
      with open(f, 'rb') as fh:
        yield fh

    return cls._meta_load(opener, config_paths, seed_values)

  @classmethod
  def _meta_load(cls, open_ctx, config_items, seed_values=None):
    if not config_items:
      return _EmptyConfig()

    single_file_configs = []
    for config_item in config_items:
      parser = cls._create_parser(seed_values)
      with open_ctx(config_item) as ini:
        content = ini.read()
        content_digest = sha1(content).hexdigest()
        parser.read_string(content.decode('utf-8'))
      config_path = config_item.path if hasattr(config_item, 'path') else config_item
      single_file_configs.append(_SingleFileConfig(config_path, content_digest, parser))

    return _ChainedConfig(tuple(reversed(single_file_configs)))

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

    return configparser.ConfigParser(all_seed_values)

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
  def configs(self):
    """Returns the underlying single-file configs represented by this object."""
    raise NotImplementedError()

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


class _EmptyConfig(datatype([]), Config):
  """A dummy config with no data at all."""

  def sources(self):
    return []

  def configs(self):
    return []

  def sections(self):
    return []

  def has_section(self, section):
    return False

  def has_option(self, section, option):
    return False

  def get_value(self, section, option):
    return None

  def get_source_for_option(self, section, option):
    return None


class _SingleFileConfig(Config):
  """Config read from a single file.

  NB: In order to have:
    1. a specialized implementation of __eq__ and __hash__ that avoids comparing file contents
    2. equality ignore the ConfigParser instance
  ...this is not a datatype.
  """

  def __init__(self, configpath, content_digest, configparser):
    super(_SingleFileConfig, self).__init__()
    self.configpath = configpath
    self.content_digest = content_digest
    self.configparser = configparser

  def configs(self):
    return [self]

  def sources(self):
    return [self.configpath]

  def sections(self):
    return self.configparser.sections()

  def has_section(self, section):
    return self.configparser.has_section(section)

  def has_option(self, section, option):
    return self.configparser.has_option(section, option)

  def get_value(self, section, option):
    return self.configparser.get(section, option)

  def get_source_for_option(self, section, option):
    if self.has_option(section, option):
      return self.sources()[0]
    return None

  def __eq__(self, other):
    return self.configpath == other.configpath and self.content_digest == other.content_digest

  def __hash__(self):
    return hash(self.content_digest)


class _ChainedConfig(datatype(['chained_configs']), Config):
  """Config read from multiple sources.

  :param configs: A tuple of Config instances to chain.
                  Later instances take precedence over earlier ones.
  """

  @property
  def _configs(self):
    return self.chained_configs

  def configs(self):
    return self.chained_configs

  def sources(self):
    # NB: Present the sources in the order we were given them.
    return list(itertools.chain.from_iterable(cfg.sources() for cfg in reversed(self._configs)))

  def sections(self):
    ret = OrderedSet()
    for cfg in self._configs:
      ret.update(cfg.sections())
    return ret

  def has_section(self, section):
    for cfg in self._configs:
      if cfg.has_section(section):
        return True
    return False

  def has_option(self, section, option):
    for cfg in self._configs:
      if cfg.has_option(section, option):
        return True
    return False

  def get_value(self, section, option):
    for cfg in self._configs:
      try:
        return cfg.get_value(section, option)
      except (configparser.NoSectionError, configparser.NoOptionError):
        pass
    if not self.has_section(section):
      raise configparser.NoSectionError(section)
    raise configparser.NoOptionError(option, section)

  def get_source_for_option(self, section, option):
    for cfg in self._configs:
      if cfg.has_option(section, option):
        return cfg.get_source_for_option(section, option)
    return None
