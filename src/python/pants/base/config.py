# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
try:
  import ConfigParser
except ImportError:
  import configparser as ConfigParser

import copy
import os
import getpass

from pants.base.build_environment import get_buildroot


class ConfigOption(object):
  """Registry of pants.ini options.

  Options are created in code, typically scoped as close to their use as possible. ::

     my_opt = ConfigOption.create(
       section='mycache',
       option='cachedir',
       help='Directory, relative to pants_workdir, of the cache directory.',
       default='mycache')

  Read an option from ``pants.ini`` with ::

     mycache_dir = os.path.join(config.get_option(config.DEFAULT_PANTS_WORKDIR),
                                config.get_option(my_opt))

  Please note `configparser <http://docs.python.org/2/library/configparser.html>`_
  is used to retrieve options, so variable interpolation and the default section
  are used as defined in the configparser docs.
  """

  class Option(object):
    """A ``pants.ini`` option."""
    def __init__(self, section, option, help, valtype, default):
      """Do not instantiate directly - use ConfigOption.create."""
      self.section = section
      self.option = option
      self.help = help
      self.valtype = valtype
      self.default = default

    def __hash__(self):
      return hash(self.section + self.option)

    def __eq__(self, other):
      if other is None:
        return False
      return True if self.section == other.section and self.option == other.option else False

    def __repr__(self):
      return '%s(%s.%s)' % (self.__class__.__name__, self.section, self.option)

  _CONFIG_OPTIONS = set()

  @classmethod
  def all(cls):
    return cls._CONFIG_OPTIONS

  @classmethod
  def create(cls, section, option, help, valtype=str, default=None):
    """Create a new ``pants.ini`` option.

    :param section: Name of section to retrieve option from.
    :param option: Name of option to retrieve from section.
    :param help: Description for display in the configuration reference.
    :param valtype: Type to cast the retrieved option to.
    :param default: Default value if undefined in the config.
    :returns: An ``Option`` suitable for use with ``Config.get_option``.
    :raises: ``ValueError`` if the option already exists.
    """
    new_opt = cls.Option(section=section,
                         option=option,
                         help=help,
                         valtype=valtype,
                         default=default)
    for existing_opt in cls._CONFIG_OPTIONS:
      if new_opt.section == existing_opt.section and new_opt.option == existing_opt.option:
        raise ValueError('Option %s.%s already exists.' % (new_opt.section, new_opt.option))
    cls._CONFIG_OPTIONS.add(new_opt)
    return new_opt


def reset_default_bootstrap_option_values(defaults):
  """Reset the bootstrap options' default values to their hard-coded defaults.

  The bootstrapping code will later overwrite these. Code that doesn't trigger bootstrapping
  (i.e., the one remaining old-style command) will get these defaults, as it did before.
  It's a code smell to update nominally static data dynamically, but this is temporary,
  and saves us having to plumb things through to all the Config.from_cache() call sites.

  This method is needed so we can call it in tests of this code, to reset state for unrelated tests.

  TODO: Remove after all direct config reads have been subsumed into the options system,
        which can pass these into Config.load() itself after bootstrapping them.
  """

  defaults.update({
    'pants_workdir': os.path.join(get_buildroot(), '.pants.d'),
    'pants_supportdir': os.path.join(get_buildroot(), 'build-support'),
    'pants_distdir': os.path.join(get_buildroot(), 'dist')
  })


class Config(object):
  """Encapsulates ini-style config file loading and access.

  Supports recursive variable substitution using standard python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """

  _defaults = {
    'buildroot': get_buildroot(),
    'homedir': os.path.expanduser('~'),
    'user': getpass.getuser(),
    'pants_bootstrapdir': os.path.expanduser('~/.pants.d'),
  }
  reset_default_bootstrap_option_values(_defaults)

  # TODO: Remove these after removing remaining references to them.

  DEFAULT_SECTION = ConfigParser.DEFAULTSECT

  DEFAULT_PANTS_WORKDIR = ConfigOption.create(
    section=DEFAULT_SECTION,
    option='pants_workdir',
    help='Directory where pants will write its intermediate output files.',
    default=os.path.join(get_buildroot(), '.pants.d'))

  class ConfigError(Exception):
    pass

  @classmethod
  def reset_default_bootstrap_option_values(cls):
    reset_default_bootstrap_option_values(cls._defaults)

  _cache = {}

  @classmethod
  def clear_cache(cls):
    cls._cache = {}

  @classmethod
  def from_cache(cls, configpath=None):
    configpath = configpath or os.path.join(get_buildroot(), 'pants.ini')
    if configpath not in cls._cache:
      cls._cache[configpath] = cls.load(configpath)
    return cls._cache[configpath]

  @classmethod
  def load(cls, configpath=None):
    """Loads a Config from the given path.

     By default this is the path to the pants.ini file in the current build root directory.
     Any defaults supplied will act as if specified in the loaded config file's DEFAULT section.
     The 'buildroot', invoking 'user' and invoking user's 'homedir' are automatically defaulted.
    """
    configpath = configpath or os.path.join(get_buildroot(), 'pants.ini')
    parser = cls.create_parser()
    with open(configpath) as ini:
      parser.readfp(ini)
    return Config(parser)

  @classmethod
  def create_parser(cls, defaults=None):
    """Creates a config parser that supports %([key-name])s value substitution.

    Any defaults supplied will act as if specified in the loaded config file's DEFAULT section and
    be available for substitutions, along with all the standard defaults defined above.
    """
    standard_defaults = copy.copy(cls._defaults)
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

  # TODO(travis): Migrate all config reads to get_option and remove other getters.
  # TODO(travis): Rename to get when other getters are removed.
  def get_option(self, option):
    if not isinstance(option, ConfigOption.Option):
      raise ValueError('Expected %s but found %s' % (ConfigOption.Option.__class__.__name__,
                                                     option))
    return self.get(section=option.section,
                    option=option.option,
                    type=option.valtype,
                    default=option.default)

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
    if val is None:
      raise Config.ConfigError('Required option %s.%s is not defined.' % (section, option))
    return val

  def has_section(self, section):
    """Return whether or not this config has the section."""
    return self.configparser.has_section(section)

  def has_option(self, section, option):
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
    if not self.has_option(section, option):
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
