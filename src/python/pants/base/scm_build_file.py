# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
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

  @classmethod
  def set_rev(cls, rev):
    cls._rev = rev

  @classmethod
  def set_scm(cls, scm):
    cls._scm = scm

  def glob1(self, path, glob):
    relpath = os.path.relpath(path, self.root_dir)
    files = self._scm.listdir(self._rev, relpath)
    return [filename for filename in files if fnmatch.fnmatch(filename, glob)]

  def source(self):
    """Returns the source code for this BUILD file."""
    with self._scm.open(self._rev, self.relpath, 'rb') as source:
      return source.read()

  def isdir(self, path):
    relpath = os.path.relpath(path, self.root_dir)
    return self._scm.isdir(self._rev, relpath)

  def isfile(self, path):
    relpath = os.path.relpath(path, self.root_dir)
    return self._scm.isfile(self._rev, relpath)

  def exists(self, path):
    relpath = os.path.relpath(path, self.root_dir)
    return self._scm.exists(self._rev, relpath)

  @classmethod
  def walk(self, root, topdown=False):
    relpath = os.path.relpath(path, self.root_dir)
    for path, dirnames, filenames in self._do_walk(relpath, topdown=topdown):
      yield (os.path.join(self.root_dir, path), dirnames, filenames)

  def _do_walk(self, root, topdown=False):
    if self._scm.isdir(path, self._rev):
      filenames = []
      dirnames = []
      for filename in listdir(path):
        path = os.path.join(root, filename)
        if self._scm.isdir(path, self._rev):
          dirnames.append(filename)
        else:
          filenames.append(filename)

      if topdown:
        yield (path, dirnames, filenames)

      for dirname in dirnames:
        for item in self._do_walk(os.path.join(root, dirname), topdown=topdown):
          yield item

      if not topdown:
        yield (path, dirnames, filenames)
