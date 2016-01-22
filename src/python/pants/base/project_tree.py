# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod

from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class ProjectTree(AbstractClass):
  """Represents project tree which is used to locate and read build files.
  Has two implementations: one backed by file system and one backed by SCM.
  """

  class InvalidBuildRootError(Exception):
    """Raised when the build_root specified to a ProjectTree is not valid."""

  def __init__(self, build_root):
    if not os.path.isabs(build_root):
      raise self.InvalidBuildRootError('ProjectTree build_root {} must be an absolute path.'.format(build_root))
    self.build_root = os.path.realpath(build_root)

  @abstractmethod
  def glob1(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob"""

  @abstractmethod
  def walk(self, relpath, topdown=True):
    """Walk the file tree rooted at `path`.  Works like os.walk but returned root value is relative path."""

  @abstractmethod
  def isdir(self, relpath):
    """Returns True if path is a directory"""

  @abstractmethod
  def isfile(self, relpath):
    """Returns True if path is a file"""

  @abstractmethod
  def exists(self, relpath):
    """Returns True if path exists"""

  @abstractmethod
  def content(self, file_relpath):
    """Returns the content for file at path."""
