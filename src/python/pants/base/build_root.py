# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.util.meta import Singleton


class BuildRoot(Singleton):
  """Represents the global workspace build root.

  By default the root of the pants workspace is the directory in which the runner script
  is located.

  This path can also be manipulated through this interface for re-location of the
  build root in tests.
  """

  class NotFoundError(Exception):
    """Raised when unable to find the current workspace build root."""

  @classmethod
  def detect_buildroot(cls):
    cwd = os.getcwd()
    # As a sanity check, verify that there's a pants runner script in the cwd.
    # Technically this check will false-positive if run in a dir that isn't the buildroot
    # but which happens to contain a file called 'pants'. But that seems unlikely in practice.
    pants_runner = os.path.join(cwd, 'pants')
    if not os.path.isfile(pants_runner):
      raise cls.NotFoundError('The current working directory does not appear to be the root of '
                              'a Pants workspace.')
    return cwd

  def __init__(self):
    self._root_dir = None

  @property
  def path(self):
    """Returns the build root for the current workspace."""
    if self._root_dir is None:
      self._root_dir = os.path.realpath(self.detect_buildroot())
    return self._root_dir

  def set_path(self, root_dir):
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
