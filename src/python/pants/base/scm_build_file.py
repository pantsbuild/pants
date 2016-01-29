# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_file import BuildFile
from pants.base.scm_project_tree import ScmProjectTree


# Deprecated, will be removed after 0.0.72. Create BuildFile with ScmFilesystem instead.
class ScmBuildFile(BuildFile):
  _rev = None
  _scm = None

  @classmethod
  def set_rev(cls, rev):
    cls._rev = rev

  @classmethod
  def set_scm(cls, scm):
    cls._scm = scm

  def __init__(self, root_dir, relpath=None, must_exist=True):
    super(ScmBuildFile, self).__init__(ScmBuildFile._get_project_tree(root_dir),
                                       relpath=relpath, must_exist=must_exist)

  @classmethod
  def _get_project_tree(cls, root_dir):
    return ScmProjectTree(root_dir, cls._scm, cls._rev)
