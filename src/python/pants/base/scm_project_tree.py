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
    self._scm_worktree = os.path.realpath(scm.worktree)

  def _scm_relpath(self, build_root_relpath):
    return os.path.relpath(os.path.join(self.build_root, build_root_relpath), self._scm_worktree)

  def glob1(self, dir_relpath, glob):
    files = self._reader.listdir(self._scm_relpath(dir_relpath))
    return [filename for filename in files if fnmatch.fnmatch(filename, glob)]

  def content(self, file_relpath):
    with self._reader.open(self._scm_relpath(file_relpath)) as source:
      return source.read()

  def isdir(self, relpath):
    return self._reader.isdir(self._scm_relpath(relpath))

  def isfile(self, relpath):
    return self._reader.isfile(self._scm_relpath(relpath))

  def exists(self, relpath):
    return self._reader.exists(self._scm_relpath(relpath))

  def walk(self, relpath, topdown=True):
    for path, dirnames, filenames in self._do_walk(self._scm_relpath(relpath), topdown=topdown):
      yield (os.path.relpath(os.path.join(self._scm_worktree, path), self.build_root), dirnames, filenames)

  def _do_walk(self, scm_relpath, topdown):
    """Helper method for _walk"""
    if self._reader.isdir(scm_relpath):
      filenames = []
      dirnames = []
      dirpaths = []
      for filename in self._reader.listdir(scm_relpath):
        path = os.path.join(scm_relpath, filename)
        if self._reader.isdir(path):
          dirnames.append(filename)
          dirpaths.append(path)
        else:
          filenames.append(filename)

      if topdown:
        yield (scm_relpath, dirnames, filenames)

      for dirpath in dirpaths:
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
