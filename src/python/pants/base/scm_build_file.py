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
  _file_system = None

  @classmethod
  def set_rev(cls, rev):
    cls._rev = rev
    if cls._scm:
      cls._file_system = ScmFilesystem(cls._scm, cls._rev)

  @classmethod
  def set_scm(cls, scm):
    cls._scm = scm
    if cls._rev:
      cls._file_system = ScmFilesystem(cls._scm, cls._rev)

  def __init__(self, root_dir, relpath=None, must_exist=True):
    super(ScmBuildFile, self).__init__(ScmBuildFile._file_system, root_dir, relpath=relpath, must_exist=must_exist)

  @classmethod
  def from_cache(cls, root_dir, relpath, must_exist=True):
    return ScmBuildFile.create(cls._file_system, root_dir, relpath, must_exist)

  @classmethod
  def _isdir(cls, path):
    return cls._file_system.isdir(path)

  @classmethod
  def _isfile(cls, path):
    return cls._file_system.isfile(path)

  @classmethod
  def _exists(cls, path):
    return cls._file_system.exists(path)

  @classmethod
  def _walk(cls, root_dir, relpath, topdown=False):
    return cls._file_system.walk(root_dir, relpath, topdown)
