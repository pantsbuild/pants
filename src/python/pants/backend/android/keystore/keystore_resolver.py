# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.option.config import Config


class KeystoreResolver(object):
  """Reads a keystore config.ini file and instantiate Keystore objects with the info.

  A Keystore config is an .ini file with valid syntax as parsed by Python's ConfigParser.
  Each definition requires an arbitrary [name] section followed by the following five fields:
  build_type, keystore_location, keystore_alias, keystore_password, key_password.

  The specs of these fields can be seen below in the Keystore object docstring.
  """

  class Error(Exception):
    """Indicates an invalid android distribution."""

  @classmethod
  def resolve(cls, keystore_config_file):
    """Parse a keystore config file and return a list of Keystore objects."""
    keystore_config_file = os.path.expanduser(keystore_config_file)
    try:
      keystore_config = Config.load([keystore_config_file])
    except IOError as e:
      raise KeystoreResolver.Error('Problem parsing keystore config file at {}: '
                                   '{}'.format(keystore_config_file, e))

    def create_key(key_name):
      """Instantiate Keystore objects."""
      def get_config_value(section, option):
        val = keystore_config.get(section, option)
        if val is None or val == '':
          raise KeystoreResolver.Error('Required keystore config value {}.{} is '
                                       'not defined.'.format(section, option))
        return val

      keystore = Keystore(keystore_name=key_name,
                          build_type=get_config_value(key_name, 'build_type'),
                          keystore_location=get_config_value(key_name, 'keystore_location'),
                          keystore_alias=get_config_value(key_name, 'keystore_alias'),
                          keystore_password=get_config_value(key_name, 'keystore_password'),
                          key_password=get_config_value(key_name, 'key_password'))
      return keystore

    keys = {}
    for name in keystore_config.sections():
      try:
        keys[name] = create_key(name)
      except Config.ConfigError as e:
        raise KeystoreResolver.Error(e)
    return keys


class Keystore(object):
  """Represents a keystore configuration."""

  def __init__(self,
               keystore_name=None,
               build_type=None,
               keystore_location=None,
               keystore_alias=None,
               keystore_password=None,
               key_password=None):
    """
    :param string keystore_name: Arbitrary name of keystore. I.e., the [section] in the config file.
    :param string build_type: The build type of the keystore. One of (debug, release).
    :param string keystore_location: path/to/keystore.
    :param string keystore_alias: The alias of this keystore.
    :param string keystore_password: The password for the keystore.
    :param string key_password: The password for the key.
    """

    self._type = None
    self._build_type = build_type

    self.keystore_name = keystore_name
    # The os call is robust against None b/c it was validated in KeyResolver with get_required().
    self.keystore_location = os.path.expanduser(keystore_location)
    self.keystore_alias = keystore_alias
    self.keystore_password = keystore_password
    self.key_password = key_password

  @property
  def build_type(self):
    """Return the build type of the keystore.

    Required to be either 'debug' or 'release'.
    """
    if self._type is None:
      keystore_type = self._build_type.lower()
      if keystore_type not in ('release', 'debug'):
        raise ValueError('The build_type of Android keystores must be one of (debug, release) '
                         'instead of: {0}.'.format(self._build_type))
      else:
        self._type = keystore_type
    return self._type
