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

  By default a pants workspace is defined by a root directory where a file called 'pants' -
  typically the pants runner script - lives.  This path can also be manipulated through
  this interface for re-location of the build root in tests.

  TODO: If this ever causes a problem (because some subdir that people run pants in
        legitimately contains a file called 'pants') then we can add a second check for
        an explicit sentinel file, like 'BUILDROOT'.
  """

  class NotFoundError(Exception):
    """Raised when unable to find the current workspace build root."""

  @classmethod
  def find_buildroot(cls):
    buildroot = os.path.abspath(os.getcwd())
    while not os.path.isfile(os.path.join(buildroot, 'pants')):
      parent = os.path.dirname(buildroot)
      if buildroot != parent:
        buildroot = parent
      else:
        raise cls.NotFoundError('No buildroot detected. Pants detects the buildroot by looking '
                                'for a file named pants in the cwd and its ancestors.  Typically '
                                'this is the runner script that executes pants.  If you have no '
                                'such script you can create an empty file in your buildroot.')
    return buildroot

  def __init__(self):
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
