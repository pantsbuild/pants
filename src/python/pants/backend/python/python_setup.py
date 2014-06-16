# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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
