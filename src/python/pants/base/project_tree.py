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
from twitter.common.collections import OrderedSet

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

  def __init__(self, build_root, ignore_patterns = None):
    if not os.path.isabs(build_root):
      raise self.InvalidBuildRootError('ProjectTree build_root {} must be an absolute path.'.format(build_root))
    self.build_root = os.path.realpath(build_root)
    self.ignore = PathSpec.from_lines(GitIgnorePattern, ignore_patterns if ignore_patterns else [])

  @abstractmethod
  def _glob1_raw(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob"""

  @abstractmethod
  def _listdir_raw(self, relpath):
    """Return the names of paths in the given directory."""

  @abstractmethod
  def _isdir_raw(self, relpath):
    """Returns True if path is a directory"""

  @abstractmethod
  def _isfile_raw(self, relpath):
    """returns True if path is a file"""

  @abstractmethod
  def _exists_raw(self, relpath):
    """returns True if path exists"""

  @abstractmethod
  def _content_raw(self, file_relpath):
    """Returns the content for file at path."""

  @abstractmethod
  def _relative_readlink_raw(self, relpath):
    """Execute `readlink` for the given path, which may result in a relative path."""

  @abstractmethod
  def _lstat_raw(self, relpath):
    """Without following symlinks, returns a PTStat object for the path, or None"""

  @abstractmethod
  def _walk_raw(self, relpath, topdown=True):
    """Walk the file tree rooted at `path`.  Works like os.walk but returned root value is relative path."""

  def glob1(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob"""
    if self.isignored(dir_relpath, directory=True):
      return []

    matched_files = self._glob1_raw(dir_relpath, glob)
    return self.filter_ignored(matched_files, dir_relpath)

  def listdir(self, relpath):
    """Return the names of paths in the given directory."""
    if self.isignored(relpath, directory=True):
      self._raise_access_ignored(relpath)

    names = self._listdir_raw(relpath)
    return self.filter_ignored(names, relpath)

  def isdir(self, relpath):
    """Returns True if path is a directory"""
    if self._isdir_raw(relpath):
      if not self.isignored(relpath, directory=True):
        return True

    return False

  def isfile(self, relpath):
    """Returns True if path is a file"""
    if self.isignored(relpath):
      return False
    return self._isfile_raw(relpath)

  def exists(self, relpath):
    """Returns True if path exists"""
    if self.isignored(self._append_slash_if_dir_path(relpath)):
      return False
    return self._exists_raw(relpath)

  def content(self, file_relpath):
    """Returns the content for file at path."""
    if self.isignored(file_relpath):
      self._raise_access_ignored(file_relpath)

    return self._content_raw(file_relpath)

  def relative_readlink(self, relpath):
    """Execute `readlink` for the given path, which may result in a relative path."""
    if self.isignored(self._append_slash_if_dir_path(relpath)):
      self._raise_access_ignored(relpath)
    return self._relative_readlink_raw(relpath)

  def lstat(self, relpath):
    """Without following symlinks, returns a PTStat object for the path, or None"""
    if self.isignored(self._append_slash_if_dir_path(relpath)):
      self._raise_access_ignored(relpath)

    return self._lstat_raw(relpath)

  def walk(self, relpath, topdown=True):
    """Walk the file tree rooted at `path`.  Works like os.walk but returned root value is relative path."""
    for root, dirs, files in self._walk_raw(relpath, topdown):
      matched_dirs = self.ignore.match_files([os.path.join(root, "{0}/".format(d)) for d in dirs])
      matched_files = self.ignore.match_files([os.path.join(root, f) for f in files])
      for matched_dir in matched_dirs:
        dirs.remove(fast_relpath(matched_dir, root).rstrip('/'))

      for matched_file in matched_files:
        files.remove(fast_relpath(matched_file, root))

      yield root, dirs, files

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

  def isignored(self, relpath, directory=False):
    """Returns True if path matches pants ignore pattern"""
    if directory:
      relpath = self._append_trailing_slash(relpath)
    match_result = list(self.ignore.match_files([relpath]))
    return match_result != []

  def filter_ignored(self, path_list, prefix=''):
    """Takes a list of paths and returns a list of unignored files"""
    prefixed_path_list = [self._append_slash_if_dir_path(os.path.join(prefix, item)) for item in path_list]
    ignored_paths = OrderedSet(self.ignore.match_files(prefixed_path_list))
    if len(ignored_paths) == 0:
      return path_list

    return [fast_relpath(f, prefix).rstrip('/') for f in list(OrderedSet(prefixed_path_list) - ignored_paths)]

  def _raise_access_ignored(self, relpath):
    """raise exception when accessing ignored path"""
    raise self.AccessIgnoredPathError('The path {} is ignored in {}'.format(relpath, self))

  def _append_trailing_slash(self, relpath):
    """add a trailing slash if not already has one"""
    return relpath if relpath.endswith(os.sep) else relpath + os.sep

  def _append_slash_if_dir_path(self, relpath):
    """for a dir path return a path that has a trailing slash"""
    if self._isdir_raw(relpath):
      return self._append_trailing_slash(relpath)

    return relpath


class PTStat(datatype('PTStat', ['ftype'])):
  """A simple 'Stat' facade that can be implemented uniformly across SCM and posix backends.

  :param ftype: Either 'file', 'dir', or 'link'.
  """


PTSTAT_FILE = PTStat('file')
PTSTAT_DIR  = PTStat('dir')
PTSTAT_LINK = PTStat('link')
