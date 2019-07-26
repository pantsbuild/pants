# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

from pants.util.meta import Singleton


# TODO: Even this should probably just be a new-style option?
class BuildRoot(Singleton):
  """Represents the global workspace build root.

  By default a Pants workspace is defined by a root directory where a file called 'pants' -
  typically the Pants runner script - lives. The expected file can be changed from 'pants' to
  something else, which is useful for testing. Likewise, this path can also be manipulated through
  this interface for re-location of the build root in tests.
  """

  class NotFoundError(Exception):
    """Raised when unable to find the current workspace build root."""

  def find_buildroot(self):
    buildroot = os.path.abspath(os.getcwd())
    while not os.path.isfile(os.path.join(buildroot, self._sentinel_filename)):
      parent = os.path.dirname(buildroot)
      if buildroot != parent:
        buildroot = parent
      else:
        raise self.NotFoundError('No buildroot detected. Pants detects the buildroot by looking '
                                 f'for a file named {self._sentinel_filename} in the cwd and its '
                                 'ancestors. Typically this is the runner script that executes '
                                 'Pants. If you have no such script you can create an empty file '
                                 'in your buildroot.')
    return buildroot

  def __init__(self, *, sentinel_filename: str = "pants"):
    self._sentinel_filename = sentinel_filename
    self._root_dir = None

  @property
  def path(self):
    """Returns the build root for the current workspace."""
    if self._root_dir is None:
      # This env variable is for testing purpose.
      override_buildroot = os.environ.get('PANTS_BUILDROOT_OVERRIDE', None)
      if override_buildroot:
        self._root_dir = override_buildroot
      else:
        self._root_dir = os.path.realpath(self.find_buildroot())
    return self._root_dir

  @path.setter
  def path(self, root_dir):
    """Manually establishes the build root for the current workspace."""
    path = os.path.realpath(root_dir)
    if not os.path.exists(path):
      raise ValueError(f'Build root does not exist: {root_dir}')
    self._root_dir = path

  def reset(self):
    """Clears the last calculated build root for the current workspace."""
    self._root_dir = None

  def __str__(self):
    return f'BuildRoot({self._root_dir})'

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
