# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap

from pants.util.dirutil import safe_open


class AndroidConfigUtil(object):
  """Utility methods for Pants-specific Android configurations."""

  class AndroidConfigError(Exception):
    """Indicate an error reading Android config files."""

  @classmethod
  def setup_keystore_config(cls, config):
    """Create a config file for Android keystores and seed with the default keystore.

    :param string config: Full path to the new .ini config file.
    """

    # Unless the config file in ~/.pants.d/android is deleted, this method should only run once,
    # the first time an android_target is built. What I don't like about this is that the
    # example config is only generated after the first time an android_target is built,
    # instead of being available beforehand.

    ini = textwrap.dedent(
      """
      # Android Keystore definitions. Follow this format when adding a keystore definition.
      # Each keystore has an arbitrary name and is required to have all five fields below.

      # These definitions can go anywhere in your file system, passed to pants as the option
      # '--keystore-config-location' in pants.ini or on the CLI.

      # The 'default-debug' definition is a well-known key installed along with the Android SDK.

      [default-debug]

      build_type: debug
      keystore_location: %(homedir)s/.android/debug.keystore
      keystore_alias: androiddebugkey
      keystore_password: android
      key_password: android
      """
    )

    config = os.path.expanduser(config)

    try:
      with safe_open(config, 'w') as config_file:
        config_file.write(ini)
    # OSError if no permission to make directories, IOError if there are no write perms for file.
    except (IOError, OSError) as e:
      raise cls.AndroidConfigError("Problem creating Android keystore config file: {}".format(e))
