# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual


class PythonArtifact(object):
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
    """Passes params to `setuptools.setup <https://pythonhosted.org/setuptools/setuptools.html>`_."""
    self._kw = kwargs
    self._binaries = {}

    def has(name):
      value = self._kw.get(name)
      if value is None:
        raise self.MissingArgument('PythonArtifact requires %s to be specified!' % name)
      return value

    def misses(name):
      if name in self._kw:
        raise self.UnsupportedArgument('PythonArtifact prohibits %s from being specified' % name)

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
    return '%s==%s' % (self._name, self._version)

  @property
  def setup_py_keywords(self):
    return self._kw

  @property
  def binaries(self):
    return self._binaries

  @manual.builddict()
  def with_binaries(self, *args, **kw):
    """Add binaries tagged to this artifact.

    For example: ::

      provides = setup_py(
        name = 'my_library',
        zip_safe = True
      ).with_binaries(
        my_command = pants(':my_library_bin')
      )

    This adds a console_script entry_point for the python_binary target
    pointed at by :my_library_bin.  Currently only supports
    python_binaries that specify entry_point explicitly instead of source.

    Also can take a dictionary, e.g.
    with_binaries({'my-command': pants(...)})
    """
    for arg in args:
      if isinstance(arg, dict):
        self._binaries.update(arg)
    self._binaries.update(kw)
    return self
