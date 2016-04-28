# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
from abc import abstractmethod

from pants.util.dirutil import safe_mkdir, touch
from pants.util.meta import AbstractClass


class ProjectTreeTestBase(AbstractClass):

  @abstractmethod
  def mk_project_tree(self, build_root, ignore_patterns=[]):
    """Construct a ProjectTree for the given build_root path."""
    pass

  def make_base_dir(self):
    return tempfile.mkdtemp()

  def fullpath(self, path):
    return os.path.join(self.root_dir, path)

  def makedirs(self, path):
    safe_mkdir(self.fullpath(path))

  def touch(self, path):
    touch(self.fullpath(path))

  def touch_list(self, path_list):
    for path in path_list:
      self.touch(path)

  def rm_base_dir(self):
    shutil.rmtree(self.base_dir)
