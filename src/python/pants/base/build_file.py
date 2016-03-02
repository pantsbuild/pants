# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from pathspec import PathSpec
from twitter.common.collections import OrderedSet

from pants.util.dirutil import fast_relpath
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


# Note: Significant effort has been made to keep the types BuildFile, BuildGraph, Address, and
# Target separated appropriately.  Don't add references to those other types to this module.
class BuildFile(AbstractClass):

  class BuildFileError(Exception):
    """Base class for all exceptions raised in BuildFile to make exception handling easier"""

  class MissingBuildFileError(BuildFileError):
    """Raised when a BUILD file cannot be found at the path in the spec."""

  class BadPathError(BuildFileError):
    """Raised when scan_buildfiles is called on a nonexistent directory."""

  _BUILD_FILE_PREFIX = 'BUILD'
  _PATTERN = re.compile('^{prefix}(\.[a-zA-Z0-9_-]+)?$'.format(prefix=_BUILD_FILE_PREFIX))

  _cache = {}

  @staticmethod
  def clear_cache():
    BuildFile._cache = {}

  @staticmethod
  def _cached(project_tree, relpath):
    cache_key = (project_tree, relpath)
    if cache_key not in BuildFile._cache:
      BuildFile._cache[cache_key] = BuildFile(project_tree, relpath)
    return BuildFile._cache[cache_key]

  @staticmethod
  def _is_buildfile_name(name):
    return BuildFile._PATTERN.match(name)

  @staticmethod
  def scan_build_files(project_tree, base_relpath, build_ignore_patterns=None):
    """Looks for all BUILD files
    :param project_tree: Project tree to scan in.
    :type project_tree: :class:`pants.base.project_tree.ProjectTree`
    :param base_relpath: Directory under root_dir to scan.
    :param build_ignore_patterns: .gitignore like patterns to exclude from BUILD files scan.
    :type build_ignore_patterns: pathspec.pathspec.PathSpec
    """
    if base_relpath and os.path.isabs(base_relpath):
      raise BuildFile.BadPathError('base_relpath parameter ({}) should be a relative path.'
                                   .format(base_relpath))
    if base_relpath and not project_tree.isdir(base_relpath):
      raise BuildFile.BadPathError('Can only scan directories and {0} is not a valid dir.'
                                   .format(base_relpath))
    if build_ignore_patterns and not isinstance(build_ignore_patterns, PathSpec):
      raise TypeError("build_ignore_patterns should be pathspec.pathspec.PathSpec instance, "
                      "instead {} was given.".format(type(build_ignore_patterns)))

    build_files = set()
    for root, dirs, files in project_tree.walk(base_relpath or '', topdown=True):
      excluded_dirs = list(build_ignore_patterns.match_files('{}/'.format(os.path.join(root, dirname))
                                                          for dirname in dirs))
      for subdir in excluded_dirs:
        # Remove trailing '/' from paths which were added to indicate that paths are paths to directories.
        dirs.remove(fast_relpath(subdir, root)[:-1])
      for filename in files:
        if BuildFile._is_buildfile_name(filename):
          build_files.add(os.path.join(root, filename))

    return BuildFile._build_files_from_paths(project_tree, build_files, build_ignore_patterns)

  @staticmethod
  def _build_files_from_paths(project_tree, rel_paths, build_ignore_patterns):
    if build_ignore_patterns:
      build_files_without_ignores = rel_paths.difference(build_ignore_patterns.match_files(rel_paths))
    else:
      build_files_without_ignores = rel_paths
    return OrderedSet(sorted((BuildFile._cached(project_tree, relpath) for relpath in build_files_without_ignores),
                             key=lambda build_file: build_file.full_path))

  def __init__(self, project_tree, relpath):
    """Creates a BuildFile object representing the BUILD file family at the specified path.

    :param project_tree: Project tree the BUILD file exist in.
    :type project_tree: :class:`pants.base.project_tree.ProjectTree`
    :param string relpath: The path relative to root_dir where the BUILD file is located.
    :raises IOError: if the root_dir path is not absolute.
    :raises MissingBuildFileError: if the path does not house a BUILD file.
    """
    if relpath is None:
      raise self.BuildFileError("BuildFile\'s relpath parameter cannot be None.")
    if os.path.isabs(relpath):
      raise self.BuildFileError("BuildFile\'s relpath parameter cannot be absolute.")

    self.project_tree = project_tree
    self.root_dir = project_tree.build_root

    path = os.path.join(self.root_dir, relpath)
    if not project_tree.exists(relpath):
      raise self.MissingBuildFileError('BUILD file does not exist at: {path}'
                                       .format(path=path))

    if project_tree.isdir(relpath):
      raise self.MissingBuildFileError('Path to buildfile ({buildfile}) is a directory, '
                                       'but it must be a file.'.format(buildfile=path))

    if not self._is_buildfile_name(os.path.basename(path)):
      raise self.MissingBuildFileError('{path} is not a BUILD file'
                                       .format(path=path))

    self.full_path = os.path.realpath(path)
    self.name = os.path.basename(self.full_path)
    self.parent_path = os.path.dirname(self.full_path)

    self.relpath = fast_relpath(self.full_path, self.root_dir)
    self.spec_path = os.path.dirname(self.relpath)

  @staticmethod
  def get_build_files_family(project_tree, dir_relpath, build_ignore_patterns=None):
    """Returns all the BUILD files on a path"""
    build_files = set()
    for build in sorted(project_tree.glob1(dir_relpath, '{prefix}*'.format(prefix=BuildFile._BUILD_FILE_PREFIX))):
      if BuildFile._is_buildfile_name(build) and project_tree.isfile(os.path.join(dir_relpath, build)):
        build_files.add(os.path.join(dir_relpath, build))
    return BuildFile._build_files_from_paths(project_tree, build_files, build_ignore_patterns)

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
