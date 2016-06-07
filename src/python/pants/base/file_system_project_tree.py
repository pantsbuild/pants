# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import stat
from glob import glob1

from pants.base.project_tree import Dir, File, Link, ProjectTree
from pants.util.dirutil import fast_relpath, safe_walk


# Use the built-in version of scandir/walk if possible, otherwise
# use the scandir module version
try:
  from os import scandir
except ImportError:
  from scandir import scandir


class FileSystemProjectTree(ProjectTree):
  def _join(self, relpath):
    if relpath.startswith(os.sep):
      raise ValueError('Absolute path "{}" not legal in {}.'.format(relpath, self))
    return os.path.join(self.build_root, relpath)

  def _glob1_raw(self, dir_relpath, glob):
    return glob1(self._join(dir_relpath), glob)

  def _scandir_raw(self, relpath):
    for dir_ent in scandir(self._join(relpath)):
      st_mode = dir_ent.stat(follow_symlinks=False).st_mode
      yield self._construct_stat(os.path.join(relpath, dir_ent.name), st_mode)

  def _isdir_raw(self, relpath):
    return os.path.isdir(self._join(relpath))

  def _isfile_raw(self, relpath):
    return os.path.isfile(self._join(relpath))

  def _exists_raw(self, relpath):
    return os.path.exists(self._join(relpath))

  def _content_raw(self, file_relpath):
    with open(self._join(file_relpath), 'rb') as source:
      return source.read()

  def _relative_readlink_raw(self, relpath):
    return os.readlink(self._join(relpath))

  def _lstat_raw(self, relpath):
    try:
      st_mode = os.lstat(self._join(relpath)).st_mode
      return self._construct_stat(relpath, st_mode)
    except (IOError, OSError) as e:
      if e.errno == errno.ENOENT:
        return None
      else:
        raise e

  def _walk_raw(self, relpath, topdown=True):
    def onerror(error):
      raise OSError(getattr(error, 'errno', None), 'Failed to walk below {}'.format(relpath), error)

    for root, dirs, files in safe_walk(self._join(relpath),
                                       topdown=topdown,
                                       onerror=onerror):
      yield fast_relpath(root, self.build_root), dirs, files

  def _construct_stat(self, relpath, st_mode):
    """Given a relpath and its st_mode (from stat_result), return a `project_tree.Stat`."""
    if stat.S_ISLNK(st_mode):
      return Link(relpath)
    elif stat.S_ISDIR(st_mode):
      return Dir(relpath)
    elif stat.S_ISREG(st_mode):
      return File(relpath)
    else:
      raise IOError('Unsupported file type in {}: {}'.format(self, relpath))

  def __eq__(self, other):
    return other and (type(other) == type(self)) and (self.build_root == other.build_root)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self.build_root)

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, self.build_root)
