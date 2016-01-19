# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_file import BuildFile
from pants.base.scm_file_system import ScmFilesystem


# todo: deprecate
class ScmBuildFile(BuildFile):
  _rev = None
  _scm = None

  @classmethod
  def set_rev(cls, rev):
    cls._rev = rev
    if cls._scm:
      cls._cls_file_system = ScmFilesystem(cls._scm, cls._rev)

  @classmethod
  def set_scm(cls, scm):
    cls._scm = scm
    if cls._rev:
      cls._cls_file_system = ScmFilesystem(cls._scm, cls._rev)

  def __init__(self, root_dir, relpath=None, must_exist=True):
    super(ScmBuildFile, self).__init__(ScmBuildFile._cls_file_system, root_dir, relpath=relpath, must_exist=must_exist)

  @classmethod
  def from_cache(cls, root_dir, relpath, must_exist=True):
    return ScmBuildFile.cached(cls._cls_file_system, root_dir, relpath, must_exist)
