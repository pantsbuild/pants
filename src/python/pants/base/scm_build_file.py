# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import os

from pants.base.build_file import BuildFile


class ScmBuildFile(BuildFile):
  # TODO(dturner): this cache should really be in BuildFileAddressMapper, but unfortunately this
  # class needs to access it, so it can't be moved yet.
  _cache = {}

  _rev = None
  _scm = None
  _root_dir = None

  @classmethod
  def set_rev(cls, rev):
    cls._rev = rev

  @classmethod
  def set_scm(cls, scm):
    cls._scm = scm

  @classmethod
  def _scm_worktree(cls):
    if not hasattr(cls, '_cached_scm_worktree'):
      cls._cached_scm_worktree = cls._scm.detect_worktree()
    return cls._cached_scm_worktree

  def __init__(self, root_dir, relpath=None, must_exist=True):
    super(ScmBuildFile, self).__init__(root_dir, relpath=relpath, must_exist=must_exist)

  @classmethod
  def from_cache(cls, root_dir, relpath, must_exist=True):
    key = (root_dir, relpath, must_exist)
    if key not in cls._cache:
      cls._cache[key] = cls(*key)
    return cls._cache[key]

  def glob1(self, path, glob):
    relpath = os.path.relpath(path, self._scm_worktree())
    files = self._scm.listdir(self._rev, relpath)
    return [filename for filename in files if fnmatch.fnmatch(filename, glob)]

  def source(self):
    """Returns the source code for this BUILD file."""
    relpath = os.path.relpath(self.full_path, self._scm_worktree())
    with self._scm.open(self._rev, relpath) as source:
      return source.read()

  def isdir(self, path):
    relpath = os.path.relpath(path, self._scm_worktree())
    return self._scm.isdir(self._rev, relpath)

  def isfile(self, path):
    relpath = os.path.relpath(path, self._scm_worktree())
    return self._scm.isfile(self._rev, relpath)

  def exists(self, path):
    relpath = os.path.relpath(path, self._scm_worktree())
    return self._scm.exists(self._rev, relpath)

  @classmethod
  def walk(cls, root_dir, root, topdown=False):
    scm_rootpath = os.path.relpath(root_dir, cls._scm_worktree())
    if root:
      relpath = os.path.join(scm_rootpath, root)
    else:
      relpath = scm_rootpath
    for path, dirnames, filenames in cls._do_walk(relpath, topdown=topdown):
      yield (os.path.join(cls._scm_worktree(), path), dirnames, filenames)

  @classmethod
  def _do_walk(cls, root, topdown=False):
    if cls._scm.isdir(cls._rev, root):
      filenames = []
      dirnames = []
      for filename in cls._scm.listdir(cls._rev, root):
        path = os.path.join(root, filename)
        if cls._scm.isdir(cls._rev, path):
          dirnames.append(filename)
        else:
          filenames.append(filename)

      if topdown:
        yield (root, dirnames, filenames)

      for dirname in dirnames:
        for item in cls._do_walk(os.path.join(root, dirname), topdown=topdown):
          yield item

      if not topdown:
        yield (root, dirnames, filenames)
