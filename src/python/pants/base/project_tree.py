# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod, abstractproperty

import six
from pathspec.pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

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

  def __init__(self, build_root, ignore_patterns=None):
    if not os.path.isabs(build_root):
      raise self.InvalidBuildRootError(
          'ProjectTree build_root {} must be an absolute path.'.format(build_root))
    self.build_root = os.path.realpath(build_root)
    logger.debug('ProjectTree ignore_patterns: %s', ignore_patterns)
    self.ignore_patterns = ignore_patterns if ignore_patterns else []
    self.ignore = PathSpec.from_lines(GitWildMatchPattern, self.ignore_patterns)

  @abstractmethod
  def _glob1_raw(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob."""

  @abstractmethod
  def _scandir_raw(self, relpath):
    """Return Stats relative to the root for items in the given directory."""

  @abstractmethod
  def _isdir_raw(self, relpath):
    """Returns True if path is a directory."""

  @abstractmethod
  def _isfile_raw(self, relpath):
    """Returns True if path is a file."""

  @abstractmethod
  def _exists_raw(self, relpath):
    """Returns True if path exists."""

  @abstractmethod
  def _content_raw(self, file_relpath):
    """Returns the content for file at path."""

  @abstractmethod
  def _relative_readlink_raw(self, relpath):
    """Execute `readlink` for the given path, which may result in a relative path."""

  @abstractmethod
  def _walk_raw(self, relpath, topdown=True):
    """Walk the file tree rooted at `path`.

    Works like os.walk but returned root value is relative path.
    """

  def glob1(self, dir_relpath, glob):
    """Returns a list of paths in path that match glob and are not ignored."""
    if self.isignored(dir_relpath, directory=True):
      return []

    matched_files = self._glob1_raw(dir_relpath, glob)
    prefix = self._relpath_no_dot(dir_relpath)
    return self._filter_ignored(matched_files, selector=lambda p: os.path.join(prefix, p))

  def scandir(self, relpath):
    """Return paths relative to the root, which are in the given directory and not ignored."""
    if self.isignored(relpath, directory=True):
      self._raise_access_ignored(relpath)

    return self._filter_ignored(self._scandir_raw(relpath), selector=lambda e: e.path)

  def isdir(self, relpath):
    """Returns True if path is a directory and is not ignored."""
    if self._isdir_raw(relpath):
      if not self.isignored(relpath, directory=True):
        return True

    return False

  def isfile(self, relpath):
    """Returns True if path is a file and is not ignored."""
    if self.isignored(relpath):
      return False
    return self._isfile_raw(relpath)

  def exists(self, relpath):
    """Returns True if path exists and is not ignored."""
    if self.isignored(self._append_slash_if_dir_path(relpath)):
      return False
    return self._exists_raw(relpath)

  def content(self, file_relpath):
    """Returns the content for file at path. Raises exception if path is ignored.

    Raises exception if path is ignored.
    """
    if self.isignored(file_relpath):
      self._raise_access_ignored(file_relpath)

    return self._content_raw(file_relpath)

  def relative_readlink(self, relpath):
    """Execute `readlink` for the given path, which may result in a relative path.

    Raises exception if path is ignored.
    """
    if self.isignored(self._append_slash_if_dir_path(relpath)):
      self._raise_access_ignored(relpath)
    return self._relative_readlink_raw(relpath)

  def walk(self, relpath, topdown=True):
    """Walk the file tree rooted at `path`.

    Works like os.walk but returned root value is relative path.
    Ignored paths will not be returned.
    """
    for root, dirs, files in self._walk_raw(relpath, topdown):
      matched_dirs = self.ignore.match_files([os.path.join(root, "{}/".format(d)) for d in dirs])
      matched_files = self.ignore.match_files([os.path.join(root, f) for f in files])
      for matched_dir in matched_dirs:
        dirs.remove(fast_relpath(matched_dir, root).rstrip(b'/'))

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
    """Returns True if path matches pants ignore pattern."""
    relpath = self._relpath_no_dot(relpath)
    if directory:
      relpath = self._append_trailing_slash(relpath)
    return self.ignore.match_file(relpath)

  def _filter_ignored(self, entries, selector=None):
    """Given an opaque entry list, filter any ignored entries.

    :param entries: A list or generator that produces entries to filter.
    :param selector: A function that computes a path for an entry relative to the root of the
      ProjectTree, or None to use identity.
    """
    selector = selector or (lambda x: x)
    prefixed_entries = [(self._append_slash_if_dir_path(selector(entry)), entry)
                          for entry in entries]
    ignored_paths = set(self.ignore.match_files(path for path, _ in prefixed_entries))
    return [entry for path, entry in prefixed_entries if path not in ignored_paths]

  def _relpath_no_dot(self, relpath):
    return relpath.lstrip(b'./') if relpath != b'.' else b''

  def _raise_access_ignored(self, relpath):
    """Raises exception when accessing ignored path."""
    raise self.AccessIgnoredPathError('The path {} is ignored in {}'.format(relpath, self))

  def _append_trailing_slash(self, relpath):
    """Add a trailing slash if not already has one."""
    return relpath if relpath.endswith(b'/') or len(relpath) == 0 else relpath + b'/'

  def _append_slash_if_dir_path(self, relpath):
    """For a dir path return a path that has a trailing slash."""
    if self._isdir_raw(relpath):
      return self._append_trailing_slash(relpath)

    return relpath


class Stat(AbstractClass):
  """An existing filesystem path with a known type, relative to the ProjectTree's buildroot.

  Note that in order to preserve these invariants, end-user functions should never directly
  instantiate Stat instances.
  """

  @abstractproperty
  def path(self):
    """:returns: The string path for this Stat."""


class File(datatype('File', ['path']), Stat):
  """A file."""

  def __new__(cls, path):
    return super(File, cls).__new__(cls, six.binary_type(path))


class Dir(datatype('Dir', ['path']), Stat):
  """A directory."""

  def __new__(cls, path):
    return super(Dir, cls).__new__(cls, six.binary_type(path))


class Link(datatype('Link', ['path']), Stat):
  """A symbolic link."""

  def __new__(cls, path):
    return super(Link, cls).__new__(cls, six.binary_type(path))
