# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import logging
import os
from abc import abstractmethod
from glob import glob1

from pants.util.dirutil import safe_walk
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


# Note: Significant effort has been made to keep the types BuildFile, BuildGraph, Address, and
# Target separated appropriately.  Don't add references to those other types to this module.
class Filesystem(AbstractClass):
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


class IoFilesystem(Filesystem):
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
    return other and (type(other) == type(self))

  def __hash__(self):
    return hash(self.__repr__().__hash__())

  def __repr__(self):
    return '{}()'.format(self.__class__.__name__)


class ScmFilesystem(Filesystem):
  def __init__(self, scm, rev):
    self._scm = scm
    self._rev = rev
    self._reader = scm.repo_reader(rev)

  def _scm_worktree(cls):
    if not hasattr(cls, '_cached_scm_worktree'):
      cls._cached_scm_worktree = os.path.realpath(cls._scm.detect_worktree())
    return cls._cached_scm_worktree

  def glob1(self, path, glob):
    """Returns a list of paths in path that match glob"""
    relpath = os.path.relpath(path, self._scm_worktree())
    files = self._reader.listdir(relpath)
    return [filename for filename in files if fnmatch.fnmatch(filename, glob)]

  def source(self, path):
    """Returns the source code for this BUILD file."""
    relpath = os.path.relpath(self.path, self._scm_worktree())
    with self._reader.open(relpath) as source:
      return source.read()

  def isdir(self, path):
    """Returns True if path is a directory"""
    relpath = os.path.relpath(path, self._scm_worktree())
    return self._reader.isdir(relpath)

  def isfile(self, path):
    """Returns True if path is a file"""
    relpath = os.path.relpath(path, self._scm_worktree())
    return self._reader.isfile(relpath)

  def exists(self, path):
    """Returns True if path exists"""
    relpath = os.path.relpath(path, self._scm_worktree())
    return self._reader.exists(relpath)

  def walk(self, root_dir, root, topdown=False):
    """Walk a file tree.  If root is non-empty, the absolute path of the
    tree is root_dir/root; else it is just root_dir.

    Works like os.walk.
    """
    worktree = self._scm_worktree()
    scm_rootpath = os.path.relpath(os.path.realpath(root_dir), worktree)

    if root:
      relpath = os.path.join(scm_rootpath, root)
    else:
      relpath = scm_rootpath
    for path, dirnames, filenames in self._do_walk(relpath, topdown=topdown):
      yield (os.path.join(worktree, path), dirnames, filenames)

  def _do_walk(self, root, topdown=False):
    """Helper method for _walk"""
    if self._reader.isdir(root):
      filenames = []
      dirnames = []
      dirpaths = []
      for filename in self._reader.listdir(root):
        path = os.path.join(root, filename)
        if self._reader.isdir(path):
          dirnames.append(filename)
          dirpaths.append(path)
        else:
          filenames.append(filename)

      if topdown:
        yield (root, dirnames, filenames)

      for dirpath in dirpaths:
        for item in self._do_walk(dirpath, topdown=topdown):
          yield item

      if not topdown:
        yield (root, dirnames, filenames)

  def __eq__(self, other):
    return other and \
           (type(other) == type(self)) and \
           (self._scm == other._scm) and \
           (self._rev == other._rev)

  def __hash__(self):
    return hash(self._scm) ^ hash(self._rev)

  def __repr__(self):
    return '{}({}, {})'.format(self.__class__.__name__, self._scm, self._rev)
