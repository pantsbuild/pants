# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import logging
import os

from pants.base.project_tree import ProjectTree


logger = logging.getLogger(__name__)


class ScmProjectTree(ProjectTree):
  def __init__(self, build_root, scm, rev):
    super(ScmProjectTree, self).__init__(build_root)
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
