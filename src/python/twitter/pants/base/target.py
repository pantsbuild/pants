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
import collections

from twitter.common.collections import OrderedSet

from address import Address
from parse_context import ParseContext

class TargetDefinitionException(Exception):
  """Thrown on errors in target definitions."""
  def __init__(self, target, msg):
    Exception.__init__(self, 'Error in target %s: %s' % (target.address, msg))


class Target(object):
  """The baseclass for all pants targets.  Handles registration of a target amongst all parsed
  targets as well as location of the target parse context."""

  _targets_by_address = {}
  _addresses_by_buildfile = collections.defaultdict(OrderedSet)

  @classmethod
  def get_all_addresses(cls, buildfile):
    """Returns all of the target addresses in the specified buildfile if already parsed; otherwise,
    parses the buildfile to find all the addresses it contains and then returns them."""

    def lookup():
      if buildfile in Target._addresses_by_buildfile:
        return Target._addresses_by_buildfile[buildfile]
      else:
        return None

    addresses = lookup()
    if addresses:
      return addresses
    else:
      ParseContext(buildfile).parse()
      return lookup()

  @classmethod
  def get(cls, address):
    """Returns the specified module target if already parsed; otherwise, parses the buildfile in the
    context of its parent directory and returns the parsed target."""

    def lookup():
      return Target._targets_by_address[address] if address in Target._targets_by_address else None

    target = lookup()
    if target:
      return target
    else:
      ParseContext(address.buildfile).parse()
      return lookup()

  def __init__(self, name, is_meta):
    self.name = name
    self.is_meta = is_meta
    self.is_codegen = False

    self.address = self.locate()
    self._id = self._create_id()
    self.register()

  def _create_id(self):
    """Generates a unique identifer for the BUILD target.  The generated id is safe for use as a
    a path name on unix systems."""

    buildfile_relpath = os.path.dirname(self.address.buildfile.relpath)
    if buildfile_relpath is '.':
      return self.name
    else:
      return "%s.%s" % (buildfile_relpath.replace(os.sep, '.'), self.name)

  def locate(self):
    parse_context = ParseContext.locate()
    return Address(parse_context.buildfile, self.name, self.is_meta)

  def register(self):
    existing = Target._targets_by_address.get(self.address)
    if existing and existing.address.buildfile != self.address.buildfile:
      raise KeyError("%s already defined in a sibling BUILD file: %s" % (
        self.address,
        existing.address,
      ))

    Target._targets_by_address[self.address] = self
    Target._addresses_by_buildfile[self.address.buildfile].add(self.address)

  def resolve(self):
    yield self

  def walk(self, work, predicate = None):
    """Performs a walk of this target's dependency graph visiting each node exactly once.  If a
    predicate is supplied it will be used to test each target before handing the target to work and
    descending.  Work can return targets in which case these will be added to the walk candidate set
    if not already walked."""

    self._walk(set(), work, predicate)

  def _walk(self, walked, work, predicate = None):
    for target in self.resolve():
      if target not in walked:
        walked.add(target)
        if not predicate or predicate(target):
          additional_targets = work(target)
          target._walk(walked, work, predicate)
          if additional_targets:
            for additional_target in additional_targets:
              additional_target._walk(walked, work, predicate)

  def do_in_context(self, work):
    return ParseContext(self.address.buildfile).do_in_context(work)

  def __eq__(self, other):
    result = other and (
      type(self) == type(other)) and (
      self.address == other.address)
    return result

  def __hash__(self):
    return hash(self.address)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s(%s)" % (type(self).__name__, self.address)

