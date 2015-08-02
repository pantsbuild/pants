# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
from hashlib import sha1

from pants.base.build_manual import manual
from pants.base.payload_field import PayloadField


class PythonArtifact(PayloadField):
  """Represents a Python setup.py-based project."""
  class MissingArgument(Exception): pass

  class UnsupportedArgument(Exception): pass

  UNSUPPORTED_ARGS = frozenset([
    'data_files',
    'package_dir',
    'package_data',
    'packages',
  ])

  def __init__(self, **kwargs):
    """
    :param kwargs: Passed to `setuptools.setup
       <https://pythonhosted.org/setuptools/setuptools.html>`_."""
    self._kw = kwargs
    self._binaries = {}

    def has(name):
      value = self._kw.get(name)
      if value is None:
        raise self.MissingArgument('PythonArtifact requires {} to be specified!'.format(name))
      return value

    def misses(name):
      if name in self._kw:
        raise self.UnsupportedArgument('PythonArtifact prohibits {} from being specified'.format(name))

    self._version = has('version')
    self._name = has('name')
    for arg in self.UNSUPPORTED_ARGS:
      misses(arg)

  @property
  def name(self):
    return self._name

  @property
  def version(self):
    return self._version

  @property
  def key(self):
    return '{}=={}'.format(self._name, self._version)

  @property
  def setup_py_keywords(self):
    return self._kw

  @property
  def binaries(self):
    return self._binaries

  def _compute_fingerprint(self):
    return sha1(json.dumps((self._kw, self._binaries),
                           ensure_ascii=True,
                           allow_nan=False,
                           sort_keys=True)).hexdigest()

  @manual.builddict()
  def with_binaries(self, *args, **kw):
    """Add binaries tagged to this artifact.

    For example: ::

      provides = setup_py(
        name = 'my_library',
        zip_safe = True
      ).with_binaries(
        my_command = ':my_library_bin'
      )

    This adds a console_script entry_point for the python_binary target
    pointed at by :my_library_bin.  Currently only supports
    python_binaries that specify entry_point explicitly instead of source.

    Also can take a dictionary, e.g.
    with_binaries({'my-command': ':my_library_bin'})
    """
    for arg in args:
      if isinstance(arg, dict):
        self._binaries.update(arg)
    self._binaries.update(kw)
    return self
