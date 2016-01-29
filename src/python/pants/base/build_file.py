# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from twitter.common.collections import OrderedSet

from pants.base.deprecated import deprecated
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.util.dirutil import fast_relpath
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

  class BadPathError(BuildFileError):
    """Raised when scan_buildfiles is called on a nonexistent directory."""
    pass

  _BUILD_FILE_PREFIX = 'BUILD'
  _PATTERN = re.compile('^{prefix}(\.[a-zA-Z0-9_-]+)?$'.format(prefix=_BUILD_FILE_PREFIX))

  _cache = {}

  @staticmethod
  def clear_cache():
    BuildFile._cache = {}

  @staticmethod
  def _cached(project_tree, relpath, must_exist=True):
    cache_key = (project_tree, relpath, must_exist)
    if cache_key not in BuildFile._cache:
      BuildFile._cache[cache_key] = BuildFile(project_tree, relpath, must_exist)
    return BuildFile._cache[cache_key]

  @staticmethod
  def _is_buildfile_name(name):
    return BuildFile._PATTERN.match(name)

  # TODO(tabishev): Remove after transition period.
  @classmethod
  def _get_project_tree(cls, root_dir):
    raise NotImplementedError()

  @classmethod
  @deprecated('0.0.72', hint_message='Use scan_build_files instead.')
  def scan_buildfiles(cls, root_dir, base_path=None, spec_excludes=None):
    if base_path and os.path.isabs(base_path):
      base_path = fast_relpath(base_path, root_dir)
    return cls.scan_build_files(cls._get_project_tree(root_dir), base_path, spec_excludes)

  @classmethod
  @deprecated('0.0.72')
  def from_cache(cls, root_dir, relpath, must_exist=True):
    return BuildFile._cached(cls._get_project_tree(root_dir), relpath, must_exist)

  @staticmethod
  def scan_build_files(project_tree, base_relpath, spec_excludes=None):
    """Looks for all BUILD files
    :param project_tree: Project tree to scan in.
    :type project_tree: :class:`pants.base.project_tree.ProjectTree`
    :param base_relpath: Directory under root_dir to scan.
    :param spec_excludes: List of paths to exclude from the scan.  These can be absolute paths
      or paths that are relative to the root_dir.
    """

    def relativize(paths, project_tree):
      for path in paths:
        if os.path.isabs(path):
          realpath = os.path.realpath(path)
          if realpath.startswith(project_tree.build_root):
            yield fast_relpath(realpath, project_tree.build_root)
        else:
          yield path

    def find_excluded(root, dirnames, exclude_roots):
      """Removes any of the directories specified in exclude_roots from dirs.
      """
      to_remove = set()
      for dirname in dirnames:
        if os.path.join(root, dirname) in exclude_roots or (root == '.' and (dirname in exclude_roots)):
          to_remove.add(dirname)
      return to_remove

    if base_relpath and os.path.isabs(base_relpath):
      raise Exception('base_relpath parameter should be a relative path.')

    if base_relpath and not project_tree.isdir(base_relpath):
      raise BuildFile.BadPathError('Can only scan directories and {0} is not a valid dir'
                                   .format(base_relpath))

    buildfiles = []
    if spec_excludes:
      exclude_roots = set(relativize(spec_excludes, project_tree))
    else:
      exclude_roots = set()

    for root, dirs, files in project_tree.walk(base_relpath or '', topdown=True):
      to_remove = find_excluded(root, dirs, exclude_roots)
      # For performance, ignore hidden dirs such as .git, .pants.d and .local_artifact_cache.
      to_remove.update(d for d in dirs if d.startswith('.'))
      for subdir in to_remove:
        dirs.remove(subdir)
      for filename in files:
        if BuildFile._is_buildfile_name(filename):
          buildfiles.append(BuildFile._cached(project_tree, os.path.join(root, filename)))
    return OrderedSet(sorted(buildfiles, key=lambda buildfile: buildfile.full_path))

  def __init__(self, project_tree, relpath, must_exist=True):
    """Creates a BuildFile object representing the BUILD file family at the specified path.

    :param project_tree: Project tree the BUILD file exist in.
    :type project_tree: :class:`pants.base.project_tree.ProjectTree`
    :param string relpath: The path relative to root_dir where the BUILD file is found - this can
        either point directly at the BUILD file or else to a directory which contains BUILD files.
    :param bool must_exist: If True, at least one BUILD file must exist at the given location or
        else an` `MissingBuildFileError` is thrown
    :raises IOError: if the root_dir path is not absolute.
    :raises MissingBuildFileError: if the path does not house a BUILD file and must_exist is `True`.
    """

    if not must_exist:
      logger.warn('BuildFile\'s must_exist parameter is deprecated and will be removed in 0.0.74 release. '
                  'BuildFile should be created from existing file only.')
    if relpath is None:
      logger.warn('BuildFile\'s relpath parameter is deprecated and will be removed in 0.0.74 release. '
                  'BuildFile should be created with not None relpath only.')

    self.project_tree = project_tree
    self.root_dir = project_tree.build_root

    path = os.path.join(self.root_dir, relpath) if relpath else self.root_dir
    self._build_basename = self._BUILD_FILE_PREFIX

    if project_tree.isdir(fast_relpath(path, self.root_dir)):
      logger.warn('BuildFile creation using folder path is deprecated and will be removed in 0.0.74 release. '
                  'BuildFile should be created from path to file only.')

    if project_tree.isdir(fast_relpath(path, self.root_dir)):
      buildfile = os.path.join(path, self._build_basename)
    else:
      buildfile = path

    # There is no BUILD file without a prefix so select any viable sibling
    buildfile_relpath = fast_relpath(buildfile, self.root_dir)
    if not project_tree.exists(buildfile_relpath) or project_tree.isdir(buildfile_relpath):
      relpath = os.path.dirname(buildfile_relpath)
      for build in self.project_tree.glob1(relpath, '{prefix}*'.format(prefix=self._BUILD_FILE_PREFIX)):
        if self._is_buildfile_name(build) and self.project_tree.isfile(os.path.join(relpath, build)):
          self._build_basename = build
          buildfile = os.path.join(path, self._build_basename)
          buildfile_relpath = fast_relpath(buildfile, self.root_dir)
          break

    if must_exist:
      if not project_tree.exists(buildfile_relpath):
        raise self.MissingBuildFileError('BUILD file does not exist at: {path}'
                                         .format(path=buildfile))

      # If a build file must exist then we want to make sure it's not a dir.
      # In other cases we are ok with it being a dir, for example someone might have
      # repo/scripts/build/doit.sh.
      if project_tree.isdir(buildfile_relpath):
        raise self.MissingBuildFileError('Path to buildfile ({buildfile}) is a directory, '
                                         'but it must be a file.'.format(buildfile=buildfile))

      if not self._is_buildfile_name(os.path.basename(buildfile)):
        raise self.MissingBuildFileError('{path} is not a BUILD file'
                                         .format(path=buildfile))

    self.full_path = os.path.realpath(buildfile)

    self.name = os.path.basename(self.full_path)
    self.parent_path = os.path.dirname(self.full_path)

    self.relpath = fast_relpath(self.full_path, self.root_dir)
    self.spec_path = os.path.dirname(self.relpath)

  @deprecated('0.0.72')
  def file_exists(self):
    """Returns True if this BuildFile corresponds to a real BUILD file on disk."""
    return self.project_tree.exists(self.relpath) and self.project_tree.isfile(self.relpath)

  @deprecated('0.0.72')
  def descendants(self, spec_excludes=None):
    """Returns all BUILD files in descendant directories of this BUILD file's parent directory."""

    descendants = BuildFile.scan_build_files(self.project_tree,
                                             fast_relpath(self.parent_path, self.root_dir),
                                             spec_excludes=spec_excludes)
    for sibling in self.family():
      descendants.discard(sibling)
    return descendants

  @deprecated('0.0.72')
  def ancestors(self):
    """Returns all BUILD files in ancestor directories of this BUILD file's parent directory."""

    parent_buildfiles = OrderedSet()
    parentdir = fast_relpath(self.parent_path, self.root_dir)
    while parentdir != '':
      parentdir = os.path.dirname(parentdir)
      parent_buildfiles.update(BuildFile.get_build_files_family(self.project_tree, parentdir))
    return parent_buildfiles

  @deprecated('0.0.72')
  def siblings(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file not including
    this BUILD file itself"""

    for build in BuildFile.get_build_files_family(self.project_tree,
                                                  fast_relpath(self.parent_path, self.root_dir)):
      if self != build:
        yield build

  @staticmethod
  def get_build_files_family(project_tree, dir_relpath):
    """Returns all the BUILD files on a path"""
    for build in sorted(project_tree.glob1(dir_relpath, '{prefix}*'.format(prefix=BuildFile._BUILD_FILE_PREFIX))):
      if BuildFile._is_buildfile_name(build) and project_tree.isfile(os.path.join(dir_relpath, build)):
        yield BuildFile._cached(project_tree, os.path.join(dir_relpath, build))

  @deprecated('0.0.72', hint_message='Use get_build_files_family instead.')
  def family(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file including this
    BUILD file itself.  The family forms a single logical BUILD file composed of the canonical BUILD
    file if it exists and sibling build files each with their own extension, eg: BUILD.extras."""
    return BuildFile.get_build_files_family(self.project_tree, os.path.dirname(self.relpath))

  def source(self):
    """Returns the source code for this BUILD file."""
    return self.project_tree.content(self.relpath)

  def code(self):
    """Returns the code object for this BUILD file."""
    return compile(self.source(), self.full_path, 'exec', flags=0, dont_inherit=True)

  def __eq__(self, other):
    return (
      (type(other) == type(self)) and
      (self.full_path == other.full_path) and
      (self.project_tree == other.project_tree))

  def __hash__(self):
    return hash((self.project_tree, self.full_path))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return '{}({}, {})'.format(self.__class__.__name__, self.relpath, self.project_tree)


# Deprecated, will be removed after 0.0.72. Create BuildFile with IoFilesystem instead.
class FilesystemBuildFile(BuildFile):
  def __init__(self, root_dir, relpath=None, must_exist=True):
    super(FilesystemBuildFile, self).__init__(FilesystemBuildFile._get_project_tree(root_dir),
                                              relpath=relpath, must_exist=must_exist)

  @classmethod
  def _get_project_tree(cls, root_dir):
    return FileSystemProjectTree(root_dir)
