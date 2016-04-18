# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from glob import glob1

from pants.base.project_tree import ProjectTree
from pants.util.dirutil import fast_relpath, safe_walk


class FileSystemProjectTree(ProjectTree):
  def glob1(self, dir_relpath, glob):
    ret_list = []

    if self.isignored(dir_relpath):
      return ret_list

    for matched_file in glob1(os.path.join(self.build_root, dir_relpath), glob):
      if not self.isignored(os.path.join(dir_relpath, matched_file)):
        ret_list.append(matched_file)

    return ret_list

  def content(self, file_relpath):
    if self.isignored(file_relpath):
      return ""
    with open(os.path.join(self.build_root, file_relpath), 'rb') as source:
      return source.read()

  def isdir(self, relpath):
    if self.isignored(relpath):
      return False
    return os.path.isdir(os.path.join(self.build_root, relpath))

  def isfile(self, relpath):
    if self.isignored(relpath):
      return False
    return os.path.isfile(os.path.join(self.build_root, relpath))

  def exists(self, relpath):
    if self.isignored(relpath):
      return False
    return os.path.exists(os.path.join(self.build_root, relpath))

  def walk(self, relpath, topdown=True):
    def onerror(error):
      raise OSError(getattr(error, 'errno', None), 'Failed to walk below {}'.format(relpath), error)
    for root, dirs, files in safe_walk(os.path.join(self.build_root, relpath),
                                       topdown=topdown,
                                       onerror=onerror):
      rel_root = fast_relpath(root, self.build_root)
      matched_dirs = self.ignore.match_files([os.path.join(rel_root, "{0}/".format(d)) for d in dirs])
      matched_files = self.ignore.match_files([os.path.join(rel_root, f) for f in files])
      for matched_dir in matched_dirs:
        dirs.remove(matched_dir.replace(rel_root, '').strip('/'))

      for matched_file in matched_files:
        files.remove(matched_file.replace(rel_root, '').strip('/'))

      yield rel_root, dirs, files

  def __eq__(self, other):
    return other and (type(other) == type(self)) and (self.build_root == other.build_root)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self.build_root)

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, self.build_root)
