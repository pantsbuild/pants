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
  """A class used to abstract filesystem behaviour needed to load build files.
  Currently regular filesystem or SCM are supported.
  """

  def __init__(self, build_root):
    self.build_root = build_root

  @abstractmethod
  def glob1(self, path, glob):
    """Returns a list of paths in path that match glob"""

  @abstractmethod
  def walk(self, root_dir, relpath, topdown=False):
    """Walk the file tree rooted at `path`.  Works like os.walk."""

  @abstractmethod
  def isdir(self, path):
    """Returns True if path is a directory"""
    raise NotImplementedError()

  @abstractmethod
  def isfile(self, path):
    """Returns True if path is a file"""

  @abstractmethod
  def exists(self, path):
    """Returns True if path exists"""

  @abstractmethod
  def source(self, path):
    """Returns the source code for this BUILD file."""

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self.__repr__())


class FileSystemProjectTree(ProjectTree):
  def glob1(self, path, glob):
    return glob1(path, glob)

  def source(self, path):
    with open(path, 'rb') as source:
      return source.read()

  def isdir(self, path):
    return os.path.isdir(path)

  def isfile(self, path):
    return os.path.isfile(path)

  def exists(self, path):
    return os.path.exists(path)

  def walk(self, root_dir, relpath, topdown=False):
    path = os.path.join(root_dir, relpath)
    return safe_walk(path, topdown=True)

  def __eq__(self, other):
    return other and (type(other) == type(self)) and (self.build_root == other.build_root)

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, self.build_root)
