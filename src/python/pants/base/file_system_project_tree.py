# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import stat
from glob import glob1

from pants.base.project_tree import ProjectTree, PTStat
from pants.util.dirutil import fast_relpath, safe_walk


class FileSystemProjectTree(ProjectTree):
  def glob1(self, dir_relpath, glob):
    return glob1(os.path.join(self.build_root, dir_relpath), glob)

  def content(self, file_relpath):
    with open(os.path.join(self.build_root, file_relpath), 'rb') as source:
      return source.read()

  def isdir(self, relpath):
    return os.path.isdir(os.path.join(self.build_root, relpath))

  def isfile(self, relpath):
    return os.path.isfile(os.path.join(self.build_root, relpath))

  def exists(self, relpath):
    return os.path.exists(os.path.join(self.build_root, relpath))

  def lstat(self, relpath):
    try:
      mode = os.lstat(os.path.join(self.build_root, relpath)).mode
      if stat.S_ISLNK(mode):
        return PTStat.LINK
      elif stat.S_ISDIR(mode):
        return PTStat.DIR
      elif stat.S_ISREG(mode):
        return PTStat.FILE
      else:
        raise IOError('Unsupported file type in {}: {}'.format(self, relpath))
    except (IOError, OSError) as e:
      if e.errno == errno.ENOENT:
        return None
      else:
        raise e

  def listdir(self, relpath):
    return os.listdir(os.path.join(self.build_root, relpath))

  def walk(self, relpath, topdown=True):
    def onerror(error):
      raise OSError(getattr(error, 'errno', None), 'Failed to walk below {}'.format(relpath), error)
    for root, dirs, files in safe_walk(os.path.join(self.build_root, relpath),
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
