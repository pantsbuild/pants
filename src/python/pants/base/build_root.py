# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.util.meta import Singleton


# TODO: Even this should probably just be a new-style option?
class BuildRoot(Singleton):
  """Represents the global workspace build root.

  By default a pants workspace is defined by a root directory where the workspace configuration
  file - 'pants.ini' - lives.  This path can also be manipulated through this interface for
  re-location of the build root in tests.
  """

  class NotFoundError(Exception):
    """Raised when unable to find the current workspace build root."""

  def __init__(self):
    self._root_dir = None

  @property
  def path(self):
    """Returns the build root for the current workspace."""
    if self._root_dir is None:
      buildroot = os.path.abspath(os.getcwd())
      while not os.path.exists(os.path.join(buildroot, 'pants.ini')):
        if buildroot != os.path.dirname(buildroot):
          buildroot = os.path.dirname(buildroot)
        else:
          raise self.NotFoundError('Could not find pants.ini!')
      self._root_dir = os.path.realpath(buildroot)
    return self._root_dir

  @path.setter
  def path(self, root_dir):
    """Manually establishes the build root for the current workspace."""
    path = os.path.realpath(root_dir)
    if not os.path.exists(path):
      raise ValueError('Build root does not exist: {}'.format(root_dir))
    self._root_dir = path

  def reset(self):
    """Clears the last calculated build root for the current workspace."""
    self._root_dir = None

  def __str__(self):
    return 'BuildRoot({})'.format(self._root_dir)

  @contextmanager
  def temporary(self, path):
    """Establishes a temporary build root, restoring the prior build root on exit."""
    if path is None:
      raise ValueError('Can only temporarily establish a build root given a path.')
    prior = self._root_dir
    self._root_dir = path
    try:
      yield
    finally:
      self._root_dir = prior
