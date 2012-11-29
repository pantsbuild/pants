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

from twitter.pants.base.build_file import BuildFile

class Address(object):
  """Represents a BUILD file target address."""

  _META_SUFFIX = '!'

  @classmethod
  def _parse_meta(cls, string):
    is_meta = string.endswith(Address._META_SUFFIX)
    parsed = string[:-1] if is_meta else string
    return parsed, is_meta

  @classmethod
  def parse(cls, root_dir, pathish, is_relative = True):
    """Parses pathish into an Address.  A pathish can be one of:
    1.) the (relative) path of a BUILD file
    2.) the (relative) path of a directory containing a BUILD file child
    3.) either of 1 or 2 with a ':[module name]' suffix
    4.) a bare ':[module name]' indicating the BUILD file to use is the one in the current directory

    If the pathish does not have a module suffix the targeted module name is taken to be the same
    name as the BUILD file's containing directory.  In this way the containing directory name
    becomes the 'default' module target for pants.

    If there is no BUILD file at the path pointed to, or if there is but the specified module target
    is not defined in the BUILD file, an IOError is raised."""

    parts = pathish.split(':') if not pathish.startswith(':') else [ '.', pathish[1:] ]
    path, is_meta = Address._parse_meta(parts[0])
    if is_relative:
      path = os.path.relpath(os.path.abspath(path), root_dir)
    buildfile = BuildFile(root_dir, path)

    if len(parts) == 1:
      parent_name = os.path.basename(os.path.dirname(buildfile.relpath))
      return Address(buildfile, parent_name, is_meta)
    else:
      target_name, is_meta = Address._parse_meta(':'.join(parts[1:]))
      return Address(buildfile, target_name, is_meta)

  def __init__(self, buildfile, target_name, is_meta):
    self.buildfile = buildfile
    self.target_name = target_name
    self.is_meta = is_meta

  def reference(self):
    """How to reference this address in a BUILD file."""
    dirname = os.path.dirname(self.buildfile.relpath)
    if os.path.basename(dirname) != self.target_name:
      ret = '%s:%s' % (dirname, self.target_name)
    else:
      ret = dirname
    return ret

  def __eq__(self, other):
    result = other and (
      type(other) == Address) and (
      self.buildfile.canonical_relpath == other.buildfile.canonical_relpath) and (
      self.target_name == other.target_name)
    return result

  def __hash__(self):
    value = 17
    value *= 37 + hash(self.buildfile.canonical_relpath)
    value *= 37 + hash(self.target_name)
    return value

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s:%s%s" % (
      self.buildfile,
      self.target_name,
      Address._META_SUFFIX if self.is_meta else ''
    )
