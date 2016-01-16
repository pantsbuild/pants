# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_file import BuildFile
from pants.base.file_system import ScmFilesystem


# todo: deprecate
class ScmBuildFile(BuildFile):
  _rev = None
  _scm = None
  _root_dir = None

  @classmethod
  def set_rev(cls, rev):
    cls._rev = rev
    if cls._scm:
      cls._reader = cls._scm.repo_reader(cls._rev)

  @classmethod
  def set_scm(cls, scm):
    cls._scm = scm
    if cls._rev:
      cls._reader = cls._scm.repo_reader(cls._rev)

  @classmethod
  def _scm_worktree(cls):
    if not hasattr(cls, '_cached_scm_worktree'):
      cls._cached_scm_worktree = os.path.realpath(cls._scm.detect_worktree())
    return cls._cached_scm_worktree

  def __init__(self, root_dir, relpath=None, must_exist=True):
    super(ScmBuildFile, self).__init__(ScmFilesystem(root_dir, ScmBuildFile._scm, ScmBuildFile._rev),
                                       root_dir, relpath=relpath, must_exist=must_exist)

  @classmethod
  def from_cache(cls, root_dir, relpath, must_exist=True):
    return ScmBuildFile.create(ScmFilesystem(root_dir, cls._scm, cls._rev), root_dir, relpath, must_exist)

  @classmethod
  def _isdir(cls, path):
    """Returns True if path is a directory"""
    relpath = os.path.relpath(path, cls._scm_worktree())
    return cls._reader.isdir(relpath)

  @classmethod
  def _isfile(cls, path):
    """Returns True if path is a file"""
    relpath = os.path.relpath(path, cls._scm_worktree())
    return cls._reader.isfile(relpath)

  @classmethod
  def _exists(cls, path):
    """Returns True if path exists"""
    relpath = os.path.relpath(path, cls._scm_worktree())
    return cls._reader.exists(relpath)

  @classmethod
  def _walk(cls, root_dir, root, topdown=False):
    """Walk a file tree.  If root is non-empty, the absolute path of the
    tree is root_dir/root; else it is just root_dir.

    Works like os.walk.
    """
    worktree = cls._scm_worktree()
    scm_rootpath = os.path.relpath(os.path.realpath(root_dir), worktree)

    if root:
      relpath = os.path.join(scm_rootpath, root)
    else:
      relpath = scm_rootpath
    for path, dirnames, filenames in cls._do_walk(relpath, topdown=topdown):
      yield (os.path.join(worktree, path), dirnames, filenames)

  @classmethod
  def _do_walk(cls, root, topdown=False):
    """Helper method for _walk"""
    if cls._reader.isdir(root):
      filenames = []
      dirnames = []
      dirpaths = []
      for filename in cls._reader.listdir(root):
        path = os.path.join(root, filename)
        if cls._reader.isdir(path):
          dirnames.append(filename)
          dirpaths.append(path)
        else:
          filenames.append(filename)

      if topdown:
        yield (root, dirnames, filenames)

      for dirpath in dirpaths:
        for item in cls._do_walk(dirpath, topdown=topdown):
          yield item

      if not topdown:
        yield (root, dirnames, filenames)
