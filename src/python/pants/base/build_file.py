# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from glob import glob1
import logging
import marshal
import os
import re

from pex.interpreter import PythonIdentity
from twitter.common.collections import OrderedSet


logger = logging.getLogger(__name__)


class BuildFile(object):

  class MissingBuildFileError(IOError):
    pass

  _BUILD_FILE_PREFIX = 'BUILD'
  _PATTERN = re.compile('^{prefix}(\.[a-zA-Z0-9_-]+)?$'.format(prefix=_BUILD_FILE_PREFIX))

  @staticmethod
  def _get_all_build_files(path):
    """Returns all the BUILD files on a path"""
    results = []
    for build in glob1(path, '{prefix}*'.format(prefix=BuildFile._BUILD_FILE_PREFIX)):
      if BuildFile._is_buildfile_name(build):
        results.append(build)
    return sorted(results)

  @staticmethod
  def _is_buildfile_name(name):
    return BuildFile._PATTERN.match(name)

  @staticmethod
  def scan_buildfiles(root_dir, base_path=None):
    """Looks for all BUILD files under base_path"""
    buildfiles = []
    for root, dirs, files in os.walk(os.path.join(root_dir, base_path or '')):
      for filename in files:
        if BuildFile._is_buildfile_name(filename):
          buildfile_relpath = os.path.relpath(os.path.join(root, filename), root_dir)
          buildfiles.append(BuildFile(root_dir, buildfile_relpath))
    return OrderedSet(sorted(buildfiles, key=lambda buildfile: buildfile.full_path))

  def __init__(self, root_dir, relpath=None, must_exist=True):
    """Creates a BuildFile object representing the BUILD file set at the specified path.

    root_dir: The base directory of the project
    relpath: The path relative to root_dir where the BUILD file is found - this can either point
        directly at the BUILD file or else to a directory which contains BUILD files
    must_exist: If True, the specified BUILD file must exist or else an IOError is thrown
    raises IOError if the path is not absolute
    raises MissingBuildFileError if the path does not house a BUILD file and must_exist is True
    """

    if not os.path.isabs(root_dir):
      raise IOError('BuildFile root_dir {root_dir} must be an absolute path.'
                    .format(root_dir=root_dir))

    path = os.path.join(root_dir, relpath) if relpath else root_dir
    self._build_basename = BuildFile._BUILD_FILE_PREFIX
    buildfile = os.path.join(path, self._build_basename) if os.path.isdir(path) else path

    if os.path.isdir(buildfile):
      raise self.MissingBuildFileError(
        'Path to buildfile ({buildfile}) is a directory, but it must be a file.'
        .format(buildfile=buildfile))

    if must_exist:
      if not os.path.exists(os.path.dirname(buildfile)):
        raise self.MissingBuildFileError('Path to BUILD file does not exist at: {path}'
                                         .format(path=os.path.dirname(buildfile)))

    # There is no BUILD file without a prefix so select any viable sibling
    if not os.path.exists(buildfile):
      for build in BuildFile._get_all_build_files(os.path.dirname(buildfile)):
        self._build_basename = build
        buildfile = os.path.join(path, self._build_basename)
        break

    if must_exist:
      if not os.path.exists(buildfile):
        raise self.MissingBuildFileError('BUILD file does not exist at: {path}'
                                         .format(path=buildfile))

      if not BuildFile._is_buildfile_name(os.path.basename(buildfile)):
        raise self.MissingBuildFileError('{path} is not a BUILD file'
                                         .format(path=buildfile))

    self.root_dir = os.path.realpath(root_dir)
    self.full_path = os.path.realpath(buildfile)

    self.name = os.path.basename(self.full_path)
    self.parent_path = os.path.dirname(self.full_path)

    self._bytecode_path = os.path.join(self.parent_path,
                                       '.{name}.{ident}.pyc'.format(name=self.name,
                                                                    ident=PythonIdentity.get()))

    self.relpath = os.path.relpath(self.full_path, self.root_dir)
    self.spec_path = os.path.dirname(self.relpath)

  def exists(self):
    """Returns True if this BuildFile corresponds to a real BUILD file on disk."""
    return os.path.exists(self.full_path)

  def descendants(self):
    """Returns all BUILD files in descendant directories of this BUILD file's parent directory."""

    descendants = BuildFile.scan_buildfiles(self.root_dir, self.parent_path)
    for sibling in self.family():
      descendants.discard(sibling)
    return descendants

  def ancestors(self):
    """Returns all BUILD files in ancestor directories of this BUILD file's parent directory."""

    def find_parent(dir):
      parent = os.path.dirname(dir)
      for parent_buildfile in BuildFile._get_all_build_files(parent):
        buildfile = os.path.join(parent, parent_buildfile)
        if os.path.exists(buildfile) and not os.path.isdir(buildfile):
          return parent,  BuildFile(self.root_dir, os.path.relpath(buildfile, self.root_dir))
      return parent, None

    parent_buildfiles = OrderedSet()

    parentdir = os.path.dirname(self.full_path)
    visited = set()
    while parentdir not in visited and os.path.abspath(self.root_dir) != os.path.abspath(parentdir):
      visited.add(parentdir)
      parentdir, buildfile = find_parent(parentdir)
      if buildfile:
        parent_buildfiles.update(buildfile.family())

    return parent_buildfiles

  def siblings(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file not including
    this BUILD file itself"""

    for build in BuildFile._get_all_build_files(self.parent_path):
      if self.name != build :
        siblingpath = os.path.join(os.path.dirname(self.relpath), build)
        if not os.path.isdir(os.path.join(self.root_dir, siblingpath)):
          yield BuildFile(self.root_dir, siblingpath)

  def family(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file including this
    BUILD file itself.  The family forms a single logical BUILD file composed of the canonical BUILD
    file if it exists and sibling build files each with their own extension, eg: BUILD.extras."""

    yield self
    for sibling in self.siblings():
      yield sibling

  def code(self):
    """Returns the code object for this BUILD file."""
    if (os.path.exists(self._bytecode_path) and
        os.path.getmtime(self.full_path) <= os.path.getmtime(self._bytecode_path)):
      with open(self._bytecode_path, 'rb') as bytecode:
        try:
          return marshal.load(bytecode)
        except Exception as e:
          logger.warn('Failed to marshall BUILD file bytecode at {_bytecode_path}.'
                      ' Exception was: {e}'
                      .format(_bytecode_path=self._bytecode_path, e=e))

    with open(self.full_path, 'rb') as source:
      code = compile(source.read(), '<string>', 'exec', flags=0, dont_inherit=True)
      with open(self._bytecode_path, 'wb') as bytecode:
        marshal.dump(code, bytecode)
      return code

  def __eq__(self, other):
    result = other and (
      type(other) == BuildFile) and (
      self.full_path == other.full_path)
    return result

  def __hash__(self):
    return hash(self.full_path)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return self.full_path
