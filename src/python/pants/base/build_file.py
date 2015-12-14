# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re
from abc import abstractmethod
from collections import defaultdict
from glob import glob1

from twitter.common.collections import OrderedSet

from pants.util.dirutil import safe_walk
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


# Note: Significant effort has been made to keep the types BuildFile, BuildGraph, Address, and
# Target separated appropriately.  Don't add references to those other types to this module.
class BuildFile(AbstractClass):

  class BuildFileError(Exception):
    """Base class for all exceptions raised in BuildFile to make exception handling easier"""
    pass

  class MissingBuildFileError(BuildFileError):
    """Raised when a BUILD file cannot be found at the path in the spec."""
    pass

  class InvalidRootDirError(BuildFileError):
    """Raised when the root_dir specified to a BUILD file is not valid."""
    pass

  class BadPathError(BuildFileError):
    """Raised when scan_buildfiles is called on a nonexistent directory."""
    pass

  _BUILD_FILE_PREFIX = 'BUILD'
  _PATTERN = re.compile('^{prefix}(\.[a-zA-Z0-9_-]+)?$'.format(prefix=_BUILD_FILE_PREFIX))

  # Subclasses must have an _cache field.
  @classmethod
  def clear_cache(cls):
    cls._cache = {}

  @classmethod
  def from_cache(cls, root_dir, relpath, must_exist=True):
    key = (root_dir, relpath, must_exist)
    if key not in cls._cache:
      cls._cache[key] = cls(*key)
    return cls._cache[key]

  @abstractmethod
  def _glob1(self, path, glob):
    """Returns a list of paths in path that match glob"""

  def _get_all_build_files(self, path):
    """Returns all the BUILD files on a path"""
    results = []
    for build in self._glob1(path, '{prefix}*'.format(prefix=self._BUILD_FILE_PREFIX)):
      if self._is_buildfile_name(build) and self._isfile(os.path.join(path, build)):
        results.append(build)
    return sorted(results)

  @classmethod
  def _is_buildfile_name(cls, name):
    return cls._PATTERN.match(name)

  @classmethod
  def scan_buildfiles(cls, root_dir, base_path=None, spec_excludes=None):
    """Looks for all BUILD files
    :param root_dir: the root of the repo containing sources
    :param base_path: directory under root_dir to scan
    :param spec_excludes: list of paths to exclude from the scan.  These can be absolute paths
      or paths that are relative to the root_dir.
    """

    def calc_exclude_roots(root_dir, excludes):
      """Return a map of root directories to subdirectory names suitable for a quick evaluation
      inside safe_walk()
      """
      result = defaultdict(set)
      for exclude in excludes:
        if exclude:
          if os.path.isabs(exclude):
            exclude = os.path.realpath(exclude)
          else:
            exclude = os.path.join(root_dir, exclude)
          if exclude.startswith(root_dir):
            result[os.path.dirname(exclude)].add(os.path.basename(exclude))

      return result

    def find_excluded(root, dirs, exclude_roots):
      """Removes any of the directories specified in exclude_roots from dirs.
      """
      to_remove = set()
      for exclude_root in exclude_roots:
        # root ends with a /, trim it off
        if root.rstrip('/') == exclude_root:
          for subdir in exclude_roots[exclude_root]:
            if subdir in dirs:
              to_remove.add(subdir)
      return to_remove

    root_dir = os.path.realpath(root_dir)

    if base_path and not cls._isdir(os.path.join(root_dir, base_path)):
      raise cls.BadPathError('Can only scan directories and {0} is not a valid dir'
                              .format(base_path))

    buildfiles = []
    if not spec_excludes:
      exclude_roots = {}
    else:
      exclude_roots = calc_exclude_roots(root_dir, spec_excludes)

    for root, dirs, files in cls._walk(root_dir, base_path or '', topdown=True):
      to_remove = find_excluded(root, dirs, exclude_roots)
      # For performance, ignore hidden dirs such as .git, .pants.d and .local_artifact_cache.
      # TODO: Instead of this heuristic, only walk known source_roots.  But we can't do this
      # until we're able to express source_roots in some way other than bootstrap BUILD files...
      to_remove.update(d for d in dirs if d.startswith('.'))
      for subdir in to_remove:
        dirs.remove(subdir)
      for filename in files:
        if cls._is_buildfile_name(filename):
          buildfile_relpath = os.path.relpath(os.path.join(root, filename), root_dir)
          buildfiles.append(cls.from_cache(root_dir, buildfile_relpath))
    return OrderedSet(sorted(buildfiles, key=lambda buildfile: buildfile.full_path))

  @abstractmethod
  def _walk(self, root_dir, relpath, topdown=False):
    """Walk the file tree rooted at `path`.  Works like os.walk."""

  @classmethod
  def _isdir(cls, path):
    """Returns True if path is a directory"""
    raise NotImplementedError()

  @classmethod
  def _isfile(cls, path):
    """Returns True if path is a file"""
    raise NotImplementedError()

  @classmethod
  def _exists(cls, path):
    """Returns True if path exists"""
    raise NotImplementedError()

  def __init__(self, root_dir, relpath=None, must_exist=True):
    """Creates a BuildFile object representing the BUILD file family at the specified path.

    :param string root_dir: The base directory of the project.
    :param string relpath: The path relative to root_dir where the BUILD file is found - this can
        either point directly at the BUILD file or else to a directory which contains BUILD files.
    :param bool must_exist: If True, at least one BUILD file must exist at the given location or
        else an` `MissingBuildFileError` is thrown
    :raises IOError: if the root_dir path is not absolute.
    :raises MissingBuildFileError: if the path does not house a BUILD file and must_exist is `True`.
    """

    if not os.path.isabs(root_dir):
      raise self.InvalidRootDirError('BuildFile root_dir {root_dir} must be an absolute path.'
                                     .format(root_dir=root_dir))

    self.root_dir = os.path.realpath(root_dir)

    path = os.path.join(self.root_dir, relpath) if relpath else self.root_dir
    self._build_basename = self._BUILD_FILE_PREFIX
    buildfile = os.path.join(path, self._build_basename) if self._isdir(path) else path

    # There is no BUILD file without a prefix so select any viable sibling
    if not self._exists(buildfile) or self._isdir(buildfile):
      for build in self._get_all_build_files(os.path.dirname(buildfile)):
        self._build_basename = build
        buildfile = os.path.join(path, self._build_basename)
        break

    if must_exist:
      if not self._exists(buildfile):
        raise self.MissingBuildFileError('BUILD file does not exist at: {path}'
                                         .format(path=buildfile))

      # If a build file must exist then we want to make sure it's not a dir.
      # In other cases we are ok with it being a dir, for example someone might have
      # repo/scripts/build/doit.sh.
      if self._isdir(buildfile):
        raise self.MissingBuildFileError('Path to buildfile ({buildfile}) is a directory, '
                                         'but it must be a file.'.format(buildfile=buildfile))

      if not self._is_buildfile_name(os.path.basename(buildfile)):
        raise self.MissingBuildFileError('{path} is not a BUILD file'
                                         .format(path=buildfile))

    self.full_path = os.path.realpath(buildfile)

    self.name = os.path.basename(self.full_path)
    self.parent_path = os.path.dirname(self.full_path)

    self.relpath = os.path.relpath(self.full_path, self.root_dir)
    self.spec_path = os.path.dirname(self.relpath)

  def file_exists(self):
    """Returns True if this BuildFile corresponds to a real BUILD file on disk."""
    return self._isfile(self.full_path)

  def descendants(self, spec_excludes=None):
    """Returns all BUILD files in descendant directories of this BUILD file's parent directory."""

    descendants = self.scan_buildfiles(self.root_dir, self.parent_path, spec_excludes=spec_excludes)
    for sibling in self.family():
      descendants.discard(sibling)
    return descendants

  def ancestors(self):
    """Returns all BUILD files in ancestor directories of this BUILD file's parent directory."""

    def find_parent(dir):
      parent = os.path.dirname(dir)
      for parent_buildfile in self._get_all_build_files(parent):
        buildfile = os.path.join(parent, parent_buildfile)
        return parent, self.from_cache(self.root_dir, os.path.relpath(buildfile, self.root_dir))
      return parent, None

    parent_buildfiles = OrderedSet()

    def is_root(path):
      return os.path.abspath(self.root_dir) == os.path.abspath(path)

    parentdir = os.path.dirname(self.full_path)
    visited = set()
    while parentdir not in visited and not is_root(parentdir):
      visited.add(parentdir)
      parentdir, buildfile = find_parent(parentdir)
      if buildfile:
        parent_buildfiles.update(buildfile.family())

    return parent_buildfiles

  def siblings(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file not including
    this BUILD file itself"""

    for build in self._get_all_build_files(self.parent_path):
      if self.name != build:
        siblingpath = os.path.join(os.path.dirname(self.relpath), build)
        yield self.from_cache(self.root_dir, siblingpath)

  def family(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file including this
    BUILD file itself.  The family forms a single logical BUILD file composed of the canonical BUILD
    file if it exists and sibling build files each with their own extension, eg: BUILD.extras."""

    yield self
    for sibling in self.siblings():
      yield sibling

  @abstractmethod
  def source(self):
    """Returns the source code for this BUILD file."""

  def code(self):
    """Returns the code object for this BUILD file."""
    return compile(self.source(), self.full_path, 'exec', flags=0, dont_inherit=True)

  def __eq__(self, other):
    result = other and (
      type(other) == type(self)) and (
      self.full_path == other.full_path)
    return result

  def __hash__(self):
    return hash(self.full_path)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, self.full_path)


class FilesystemBuildFile(BuildFile):
  # TODO(dturner): this cache should really be in BuildFileAddressMapper, but unfortunately this
  # class needs to access it, so it can't be moved yet.
  _cache = {}

  def _glob1(self, path, glob):
    return glob1(path, glob)

  def source(self):
    """Returns the source code for this BUILD file."""
    with open(self.full_path, 'rb') as source:
      return source.read()

  @classmethod
  def _isdir(cls, path):
    return os.path.isdir(path)

  @classmethod
  def _isfile(cls, path):
    return os.path.isfile(path)

  @classmethod
  def _exists(cls, path):
    return os.path.exists(path)

  @classmethod
  def _walk(self, root_dir, relpath, topdown=False):
    path = os.path.join(root_dir, relpath)
    return safe_walk(path, topdown=True)
