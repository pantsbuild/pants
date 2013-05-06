# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import marshal
import os
import re

from glob import glob1

from twitter.common.collections import OrderedSet
from twitter.common.python.interpreter import PythonIdentity

class BuildFile(object):
  _CANONICAL_NAME = 'BUILD'
  _PATTERN = re.compile('^%s(\.[a-z]+)?$' % _CANONICAL_NAME)

  @staticmethod
  def _is_buildfile_name(name):
    return BuildFile._PATTERN.match(name)

  @staticmethod
  def scan_buildfiles(root_dir, base_path=None):
    """Looks for all BUILD files under base_path"""

    buildfiles = []
    for root, dirs, files in os.walk(base_path if base_path else root_dir):
      for filename in files:
        if BuildFile._is_buildfile_name(filename):
          buildfile_relpath = os.path.relpath(os.path.join(root, filename), root_dir)
          buildfiles.append(BuildFile(root_dir, buildfile_relpath))
    return OrderedSet(sorted(buildfiles, key=lambda buildfile: buildfile.full_path))

  def __init__(self, root_dir, relpath, must_exist=True):
    """Creates a BuildFile object representing the BUILD file set at the specified path.

    root_dir: The base directory of the project
    relpath: The path relative to root_dir where the BUILD file is found - this can either point
        directly at the BUILD file or else to a directory which contains BUILD files
    must_exist: If True, the specified BUILD file must exist or else an IOError is thrown
    raises IOError if the specified path does not house a BUILD file and must_exist is True
    """

    path = os.path.abspath(os.path.join(root_dir, relpath))
    buildfile = os.path.join(path, BuildFile._CANONICAL_NAME) if os.path.isdir(path) else path

    if os.path.isdir(buildfile):
      raise IOError("%s is a directory" % buildfile)

    if must_exist:
      if not os.path.exists(buildfile):
        raise IOError("BUILD file does not exist at: %s" % buildfile)

      if not BuildFile._is_buildfile_name(os.path.basename(buildfile)):
        raise IOError("%s is not a BUILD file" % buildfile)

      if not os.path.exists(buildfile):
        raise IOError("BUILD file does not exist at: %s" % buildfile)

    self.root_dir = os.path.realpath(root_dir)
    self.full_path = os.path.realpath(buildfile)

    self.name = os.path.basename(self.full_path)
    self.parent_path = os.path.dirname(self.full_path)

    self._bytecode_path = os.path.join(self.parent_path, '.%s.%s.pyc' % (
      self.name, PythonIdentity.get()))

    self.relpath = os.path.relpath(self.full_path, self.root_dir)
    self.canonical_relpath = os.path.join(os.path.dirname(self.relpath), BuildFile._CANONICAL_NAME)

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
      buildfile = os.path.join(parent, BuildFile._CANONICAL_NAME)
      if os.path.exists(buildfile) and not os.path.isdir(buildfile):
        return parent, BuildFile(self.root_dir, os.path.relpath(buildfile, self.root_dir))
      else:
        return parent, None

    parent_buildfiles = OrderedSet()

    parentdir = os.path.dirname(self.full_path)
    visited = set()
    while parentdir not in visited and self.root_dir != parentdir:
      visited.add(parentdir)
      parentdir, buildfile = find_parent(parentdir)
      if buildfile:
        parent_buildfiles.update(buildfile.family())

    return parent_buildfiles

  def siblings(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file not including
    this BUILD file itself"""

    for build in glob1(self.parent_path, 'BUILD*'):
      if self.name != build and BuildFile._is_buildfile_name(build):
        siblingpath = os.path.join(os.path.dirname(self.relpath), build)
        if not os.path.isdir(os.path.join(self.root_dir, siblingpath)):
          yield BuildFile(self.root_dir, siblingpath)

  def family(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file including this
    BUILD file itself.  The family forms a single logical BUILD file composed of the canonical BUILD
    file and optional sibling build files each with their own extension, eg: BUILD.extras."""

    yield self
    for sibling in self.siblings():
      yield sibling

  def code(self):
    """Returns the code object for this BUILD file."""
    if (os.path.exists(self._bytecode_path)
        and os.path.getmtime(self.full_path) <= os.path.getmtime(self._bytecode_path)):
      with open(self._bytecode_path, 'rb') as bytecode:
        return marshal.load(bytecode)
    else:
      with open(self.full_path, 'rb') as source:
        code = compile(source.read(), self.full_path, 'exec')
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
    return self.relpath
