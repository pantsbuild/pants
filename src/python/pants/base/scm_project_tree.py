# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import logging
import os
from types import NoneType

from pants.base.project_tree import PTSTAT_DIR, PTSTAT_FILE, PTSTAT_LINK, ProjectTree
from pants.util.dirutil import fast_relpath


logger = logging.getLogger(__name__)


class ScmProjectTree(ProjectTree):
  def __init__(self, build_root, scm, rev, ignore_patterns=None):
    super(ScmProjectTree, self).__init__(build_root, ignore_patterns)
    self._scm = scm
    self._rev = rev
    self._reader = scm.repo_reader(rev)
    self._scm_worktree = os.path.realpath(scm.worktree)

  def _scm_relpath(self, build_root_relpath):
    return fast_relpath(os.path.join(self.build_root, build_root_relpath), self._scm_worktree)

  def _isdir_raw(self, relpath):
    return self._reader.isdir(self._scm_relpath(relpath))

  def glob1(self, dir_relpath, glob):
    if self.isignored(self._append_trailing_slash(dir_relpath)):
      return []

    files = self._reader.listdir(self._scm_relpath(dir_relpath))
    matched_files = [filename for filename in files if fnmatch.fnmatch(filename, glob)]
    matched_files = self.filter_ignored(
      [self._append_slash_if_dir_path(os.path.join(dir_relpath, p)) for p in matched_files]
    )
    return [fast_relpath(p, dir_relpath).rstrip('/') for p in matched_files]

  def content(self, file_relpath):
    if self.isignored(file_relpath):
      self._raise_access_ignored(file_relpath)

    with self._reader.open(self._scm_relpath(file_relpath)) as source:
      return source.read()

  def isdir(self, relpath):
    if self._isdir_raw(relpath):
      if not self.isignored(self._append_trailing_slash(relpath)):
        return True

    return False

  def isfile(self, relpath):
    if self.isignored(relpath):
      return False
    return self._reader.isfile(self._scm_relpath(relpath))

  def exists(self, relpath):
    temp_path = self._append_slash_if_dir_path(relpath)
    if self.isignored(temp_path):
      return False
    return self._reader.exists(self._scm_relpath(relpath))

  def lstat(self, relpath):
    temp_path = self._append_slash_if_dir_path(relpath)
    if self.isignored(temp_path):
      self._raise_access_ignored(relpath)

    mode = type(self._reader.lstat(self._scm_relpath(relpath)))
    if mode == NoneType:
      return None
    elif mode == self._reader.Symlink:
      return PTSTAT_LINK
    elif mode == self._reader.Dir:
      return PTSTAT_DIR
    elif mode == self._reader.File:
      return PTSTAT_FILE
    else:
      raise IOError('Unsupported file type in {}: {}'.format(self, relpath))

  def relative_readlink(self, relpath):
    temp_path = self._append_slash_if_dir_path(relpath)
    if self.isignored(temp_path):
      self._raise_access_ignored(relpath)
    return self._reader.readlink(self._scm_relpath(relpath))

  def listdir(self, relpath):
    if self.isignored(self._append_trailing_slash(relpath)):
      self._raise_access_ignored(relpath)
    return self.glob1(relpath, "*")

  def walk(self, relpath, topdown=True):
    for path, dirnames, filenames in self._do_walk(self._scm_relpath(relpath), topdown=topdown):
      rel_root = fast_relpath(os.path.join(self._scm_worktree, path), self.build_root)

      matched_dirs = self.ignore.match_files(os.path.join(rel_root, "{0}/".format(d)) for d in dirnames)
      matched_files = self.ignore.match_files(os.path.join(rel_root, f) for f in filenames)

      for matched_dir in matched_dirs:
        dirnames.remove(matched_dir.replace(rel_root, '').strip('/'))

      for matched_file in matched_files:
        filenames.remove(matched_file.replace(rel_root, '').strip('/'))

      yield (rel_root, dirnames, filenames)

  def _do_walk(self, scm_relpath, topdown):
    """Helper method for _walk"""
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
