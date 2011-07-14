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

import os
import re

from twitter.common.collections import OrderedSet
from glob import glob1

class BuildFile(object):
  _CANONICAL_NAME = 'BUILD'
  _PATTERN = re.compile('^%s(\.[a-z]+)?$' % _CANONICAL_NAME)

  @classmethod
  def _is_buildfile_name(cls, name):
    return BuildFile._PATTERN.match(name)

  @classmethod
  def scan_buildfiles(cls, root_dir, base_path = None):
    """Looks for all BUILD files under base_path"""

    buildfiles = OrderedSet()
    for root, dirs, files in os.walk(base_path if base_path else root_dir):
      for filename in files:
        if BuildFile._is_buildfile_name(filename):
          buildfile_relpath = os.path.relpath(os.path.join(root, filename), root_dir)
          buildfiles.add(BuildFile(root_dir, buildfile_relpath))
    return buildfiles

  def __init__(self, root_dir, relpath):
    """Creates a BuildFile object representing the BUILD file set at the specified path.

    root_dir: The base directory of the project
    relpath: The path relative to root_dir where the BUILD file is found - this can either point
        directly at the BUILD file or else to a directory which contains BUILD files
    raises IOError if the specified path does not house a BUILD file.
    """

    path = os.path.join(root_dir, relpath)
    buildfile = os.path.join(path, BuildFile._CANONICAL_NAME) if os.path.isdir(path) else path

    if not os.path.exists(buildfile):
      raise IOError("BUILD file does not exist at: %s" % (buildfile))

    if not BuildFile._is_buildfile_name(os.path.basename(buildfile)):
      raise IOError("%s is not a BUILD file" % buildfile)

    if os.path.isdir(buildfile):
      raise IOError("%s is a directory" % buildfile)

    if not os.path.exists(buildfile):
      raise IOError("BUILD file does not exist at: %s" % buildfile)

    self.root_dir = root_dir
    self.full_path = buildfile

    self.name = os.path.basename(self.full_path)
    self.parent_path = os.path.dirname(self.full_path)
    self.relpath = os.path.relpath(self.full_path, self.root_dir)
    self.canonical_relpath = os.path.join(os.path.dirname(self.relpath), BuildFile._CANONICAL_NAME)

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
      if os.path.exists(buildfile):
        return parent, BuildFile(self.root_dir, os.path.relpath(buildfile, self.root_dir))
      else:
        return parent, None

    parent_buildfiles = OrderedSet()

    parentdir = os.path.dirname(self.full_path)
    while parentdir != self.root_dir:
      parentdir, buildfile = find_parent(parentdir)
      if buildfile:
        parent_buildfiles.update(buildfile.family())

    return parent_buildfiles

  def siblings(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file not including
    this BUILD file itself"""

    for build in glob1(self.parent_path, 'BUILD*'):
      if self.name != build and BuildFile._is_buildfile_name(build):
        yield BuildFile(self.root_dir, os.path.join(os.path.dirname(self.relpath), build))

  def family(self):
    """Returns an iterator over all the BUILD files co-located with this BUILD file including this
    BUILD file itself.  The family forms a single logical BUILD file composed of the canonical BUILD
    file and optional sibling build files each with their own extension, eg: BUILD.extras."""

    yield self
    for sibling in self.siblings():
      yield sibling

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
