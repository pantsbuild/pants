# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import stat
from glob import glob1

from pants.base.project_tree import PTSTAT_DIR, PTSTAT_FILE, PTSTAT_LINK, ProjectTree
from pants.util.dirutil import fast_relpath, safe_walk


class FileSystemProjectTree(ProjectTree):
  def _join(self, relpath):
    if relpath.startswith(os.sep):
      raise ValueError('Absolute path "{}" not legal in {}.'.format(relpath, self))
    return os.path.join(self.build_root, relpath)

  def glob1(self, dir_relpath, glob):
    return glob1(self._join(dir_relpath), glob)

  def content(self, file_relpath):
    with open(self._join(file_relpath), 'rb') as source:
      return source.read()

  def isdir(self, relpath):
    return os.path.isdir(self._join(relpath))

  def isfile(self, relpath):
    return os.path.isfile(self._join(relpath))

  def exists(self, relpath):
    return os.path.exists(self._join(relpath))

  def lstat(self, relpath):
    try:
      mode = os.lstat(self._join(relpath)).st_mode
      if stat.S_ISLNK(mode):
        return PTSTAT_LINK
      elif stat.S_ISDIR(mode):
        return PTSTAT_DIR
      elif stat.S_ISREG(mode):
        return PTSTAT_FILE
      else:
        raise IOError('Unsupported file type in {}: {}'.format(self, relpath))
    except (IOError, OSError) as e:
      if e.errno == errno.ENOENT:
        return None
      else:
        raise e

  def relative_readlink(self, relpath):
    return os.readlink(self._join(relpath))

  def listdir(self, relpath):
    return os.listdir(self._join(relpath))

  def walk(self, relpath, topdown=True):
    def onerror(error):
      raise OSError(getattr(error, 'errno', None), 'Failed to walk below {}'.format(relpath), error)
    for root, dirs, files in safe_walk(self._join(relpath),
                                       topdown=topdown,
                                       onerror=onerror):
      yield fast_relpath(root, self.build_root), dirs, files

  def __eq__(self, other):
    return other and (type(other) == type(self)) and (self.build_root == other.build_root)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self.build_root)

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, self.build_root)
