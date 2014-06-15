# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from contextlib import contextmanager

from twitter.common.lang import Singleton


class BuildRoot(Singleton):
  """Represents the global workspace ROOT_DIR.

  By default a pants workspace is defined by a root directory where the workspace configuration
  file - 'pants.ini' - lives.  This can be overridden by exporting 'PANTS_BUILD_ROOT' in the
  environment with the path to the ROOT_DIR or manipulated through this interface.
  """

  class NotFoundError(Exception):
    """Raised when unable to find the current workspace ROOT_DIR."""

  def __init__(self):
    self._root_dir = None

  @property
  def path(self):
    """Returns the ROOT_DIR for the current workspace."""
    if self._root_dir is None:
      if 'PANTS_BUILD_ROOT' in os.environ:
        self._root_dir = os.environ['PANTS_BUILD_ROOT']
      else:
        buildroot = os.path.abspath(os.getcwd())
        while not os.path.exists(os.path.join(buildroot, 'pants.ini')):
          if buildroot != os.path.dirname(buildroot):
            buildroot = os.path.dirname(buildroot)
          else:
            raise self.NotFoundError('Could not find pants.ini!')
        self._root_dir = buildroot
    return self._root_dir

  @path.setter
  def path(self, root_dir):
    """Manually establishes the ROOT_DIR for the current workspace."""
    path = os.path.realpath(root_dir)
    if not os.path.exists(path):
      raise ValueError('Build root does not exist: %s' % root_dir)
    self._root_dir = path

  def reset(self):
    """Clears the last calculated ROOT_DIR for the current workspace."""
    self._root_dir = None

  def __str__(self):
    return 'BuildRoot(%s)' % self._root_dir

  @contextmanager
  def temporary(self, path):
    """A contextmanager that establishes a temporary ROOT_DIR, restoring the prior ROOT_DIR on
    exit."""
    if path is None:
      raise ValueError('Can only temporarily establish a build root given a path.')
    prior = self._root_dir
    self._root_dir = path
    try:
      yield
    finally:
      self._root_dir = prior
