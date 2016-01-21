# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod
from glob import glob1

from pants.util.dirutil import safe_walk
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class ProjectTree(AbstractClass):
  """A class to represent project tree which used to load build files from.
  Have two implementations: based on file system and based on SCM.
  """

  class InvalidBuildRootError(Exception):
    """Raised when the build_root specified to a ProjectTree is not valid."""
    pass

  def __init__(self, build_root):
    if not os.path.isabs(build_root):
      raise self.InvalidBuildRootError('ProjectTree build_root {} must be an absolute path.'.format(build_root))
    self.build_root = os.path.realpath(build_root)

  @abstractmethod
  def glob1(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob"""

  @abstractmethod
  def walk(self, root_dir, relpath, topdown=False):
    """Walk the file tree rooted at `path`.  Works like os.walk."""

  @abstractmethod
  def isdir(self, path):
    """Returns True if path is a directory"""
    raise NotImplementedError()

  @abstractmethod
  def isfile(self, relpath):
    """Returns True if path is a file"""

  @abstractmethod
  def exists(self, relpath):
    """Returns True if path exists"""

  @abstractmethod
  def content(self, file_relpath):
    """Returns the content for file at path."""

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self.__repr__())


class FileSystemProjectTree(ProjectTree):
  def glob1(self, dir_relpath, glob):
    return glob1(os.path.join(self.build_root, dir_relpath), glob)

  def content(self, file_relpath):
    with open(os.path.join(self.build_root, file_relpath), 'rb') as source:
      return source.read()

  def isdir(self, path):
    return os.path.isdir(path)

  def isfile(self, relpath):
    return os.path.isfile(os.path.join(self.build_root, relpath))

  def exists(self, relpath):
    return os.path.exists(os.path.join(self.build_root, relpath))

  def walk(self, root_dir, relpath, topdown=False):
    path = os.path.join(root_dir, relpath)
    return safe_walk(path, topdown=True)

  def __eq__(self, other):
    return other and (type(other) == type(self)) and (self.build_root == other.build_root)

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, self.build_root)
