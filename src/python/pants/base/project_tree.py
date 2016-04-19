# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod

from pathspec.gitignore import GitIgnorePattern
from pathspec.pathspec import PathSpec

from pants.util.dirutil import fast_relpath
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ProjectTree(AbstractClass):
  """Represents project tree which is used to locate and read build files.
  Has two implementations: one backed by file system and one backed by SCM.
  """

  class InvalidBuildRootError(Exception):
    """Raised when the build_root specified to a ProjectTree is not valid."""

  class AccessIgnoredPathError(Exception):
    """Raised when accessing a path which is ignored by pants"""

  def __init__(self, build_root, pants_ignore = None):
    if not os.path.isabs(build_root):
      raise self.InvalidBuildRootError('ProjectTree build_root {} must be an absolute path.'.format(build_root))
    self.build_root = os.path.realpath(build_root)
    self.ignore = PathSpec.from_lines(GitIgnorePattern, pants_ignore if pants_ignore else [])

  @abstractmethod
  def glob1(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob"""

  @abstractmethod
  def listdir(self, relpath):
    """Return the names of paths in the given directory."""

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
  def lstat(self, relpath):
    """Without following symlinks, returns a PTStat object for the path, or None"""

  @abstractmethod
  def relative_readlink(self, relpath):
    """Execute `readlink` for the given path, which may result in a relative path."""

  def readlink(self, relpath):
    link_path = self.relative_readlink(relpath)
    if os.path.isabs(link_path):
      raise IOError('Absolute symlinks not supported in {}: {} -> {}'.format(
        self, relpath, link_path))
    # In order to enforce that this link does not escape the build_root, we join and
    # then remove it.
    abs_normpath = os.path.normpath(os.path.join(self.build_root,
                                                 os.path.dirname(relpath),
                                                 link_path))
    return fast_relpath(abs_normpath, self.build_root)

  @abstractmethod
  def content(self, file_relpath):
    """Returns the content for file at path."""

  def isignored(self, relpath):
    """Returns True id path matches pants ignore pattern"""
    match_result = list(self.ignore.match_files([relpath]))
    return match_result != []

  def filter_ignored(self, path_list):
    """Takes a list of paths and return a list of unignored files"""
    ignored_paths = set(self.ignore.match_files(path_list))
    return list(set(path_list) - ignored_paths)


class PTStat(datatype('PTStat', ['ftype'])):
  """A simple 'Stat' facade that can be implemented uniformly across SCM and posix backends.

  :param ftype: Either 'file', 'dir', or 'link'.
  """


PTSTAT_FILE = PTStat('file')
PTSTAT_DIR  = PTStat('dir')
PTSTAT_LINK = PTStat('link')
