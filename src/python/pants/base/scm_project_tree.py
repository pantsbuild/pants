# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import logging
import os
from types import NoneType

from pants.base.deprecated import deprecated
from pants.base.project_tree import Dir, File, Link, ProjectTree
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized


logger = logging.getLogger(__name__)


class ScmProjectTree(ProjectTree):
  @deprecated('1.5.0.dev0',
              hint_message="ScmProjectTree was lightly used, and is now deprecated.")
  def __init__(self, build_root, scm, rev, ignore_patterns=None):
    super(ScmProjectTree, self).__init__(build_root, ignore_patterns)
    self._scm = scm
    self._rev = rev
    self._scm_worktree = os.path.realpath(scm.worktree)

  @property
  @memoized
  def _reader(self):
    """Make this memoized such that `ScmProjectTree` is pickable."""
    return self._scm.repo_reader(self._rev)

  def _scm_relpath(self, build_root_relpath):
    return fast_relpath(os.path.join(self.build_root, build_root_relpath), self._scm_worktree)

  def _glob1_raw(self, dir_relpath, glob):
    files = self._reader.listdir(self._scm_relpath(dir_relpath))
    return [filename for filename in files if fnmatch.fnmatch(filename, glob)]

  def _scandir_raw(self, relpath):
    # TODO: Further optimization possible.
    for name in self._reader.listdir(self._scm_relpath(relpath)):
      yield self._lstat(os.path.join(relpath, name))

  def _isdir_raw(self, relpath):
    return self._reader.isdir(self._scm_relpath(relpath))

  def _isfile_raw(self, relpath):
    return self._reader.isfile(self._scm_relpath(relpath))

  def _exists_raw(self, relpath):
    return self._reader.exists(self._scm_relpath(relpath))

  def _content_raw(self, file_relpath):
    with self._reader.open(self._scm_relpath(file_relpath)) as source:
      return source.read()

  def _relative_readlink_raw(self, relpath):
    return self._reader.readlink(self._scm_relpath(relpath))

  def _lstat(self, relpath):
    mode = type(self._reader.lstat(self._scm_relpath(relpath)))
    if mode == NoneType:
      return None
    elif mode == self._reader.Symlink:
      return Link(relpath)
    elif mode == self._reader.Dir:
      return Dir(relpath)
    elif mode == self._reader.File:
      return File(relpath)
    else:
      raise IOError('Unsupported file type in {}: {}'.format(self, relpath))

  def _walk_raw(self, relpath, topdown=True):
    for path, dirnames, filenames in self._do_walk(self._scm_relpath(relpath), topdown=topdown):
      yield fast_relpath(os.path.join(self._scm_worktree, path), self.build_root), dirnames, filenames

  def _do_walk(self, scm_relpath, topdown):
    """
    Helper method for _walk, works similarly to os.walk.
    Check https://docs.python.org/2/library/os.html#os.walk for explanation on "topdown" parameter.
    """
    if self._reader.isdir(scm_relpath):
      filenames = []
      dirnames = []

      for filename in self._reader.listdir(scm_relpath):
        path = os.path.join(scm_relpath, filename)
        if self._reader.isdir(path):
          dirnames.append(filename)
        else:
          filenames.append(filename)

      if topdown:
        yield (scm_relpath, dirnames, filenames)

      for dirname in dirnames:
        dirpath = os.path.join(scm_relpath, dirname)
        for item in self._do_walk(dirpath, topdown=topdown):
          yield item

      if not topdown:
        yield (scm_relpath, dirnames, filenames)

  def __eq__(self, other):
    return (
      (type(other) == type(self)) and
      (self.build_root == other.build_root) and
      (self._scm == other._scm) and
      (self._rev == other._rev))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash((self.build_root, self._scm, self._rev))

  def __repr__(self):
    return '{}({}, {}, {})'.format(self.__class__.__name__, self.build_root, self._scm, self._rev)
