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

import collections
import os

from twitter.common.collections import OrderedSet, maybe_list
from twitter.common.decorators import deprecated_with_warning

from twitter.pants import is_concrete
from twitter.pants.base.address import Address
from twitter.pants.base.hash_utils import hash_all
from twitter.pants.base.parse_context import ParseContext


class TargetDefinitionException(Exception):
  """Thrown on errors in target definitions."""
  def __init__(self, target, msg):
    Exception.__init__(self, 'Error in target %s: %s' % (target.address, msg))


class Target(object):
  """The baseclass for all pants targets.

  Handles registration of a target amongst all parsed targets as well as location of the target
  parse context.
  """

  _targets_by_address = {}
  _addresses_by_buildfile = collections.defaultdict(OrderedSet)

  @staticmethod
  def identify(targets):
    """Generates an id for a set of targets."""
    return Target.combine_ids(target.id for target in targets)

  @staticmethod
  def maybe_readable_identify(targets):
    """Generates an id for a set of targets.

    If the set is a single target, just use that target's id."""
    return Target.maybe_readable_combine_ids([target.id for target in targets])

  @staticmethod
  def combine_ids(ids):
    """Generates a combined id for a set of ids."""
    return hash_all(sorted(ids))  # We sort so that the id isn't sensitive to order.

  @staticmethod
  def maybe_readable_combine_ids(ids):
    """Generates combined id for a set of ids, but if the set is a single id, just use that."""
    ids = list(ids)  # We can't len a generator.
    return ids[0] if len(ids) == 1 else Target.combine_ids(ids)

  @classmethod
  def get_all_addresses(cls, buildfile):
    """Returns all of the target addresses in the specified buildfile if already parsed; otherwise,
    parses the buildfile to find all the addresses it contains and then returns them."""

    def lookup():
      if buildfile in cls._addresses_by_buildfile:
        return cls._addresses_by_buildfile[buildfile]
      else:
        return OrderedSet()

    addresses = lookup()
    if addresses:
      return addresses
    else:
      ParseContext(buildfile).parse()
      return lookup()

  @classmethod
  def _clear_all_addresses(cls):
    cls._targets_by_address = {}
    cls._addresses_by_buildfile = collections.defaultdict(OrderedSet)

  @classmethod
  def get(cls, address):
    """Returns the specified module target if already parsed; otherwise, parses the buildfile in the
    context of its parent directory and returns the parsed target."""

    def lookup():
      return cls._targets_by_address[address] if address in cls._targets_by_address else None

    target = lookup()
    if target:
      return target
    else:
      ParseContext(address.buildfile).parse()
      return lookup()

  @classmethod
  def resolve_all(cls, targets, *expected_types):
    """Yield the resolved concrete targets checking each is a subclass of one of the expected types
    if specified.
    """
    if targets:
      for target in maybe_list(targets, expected_type=Target):
        for resolved in filter(is_concrete, target.resolve()):
          if expected_types and not isinstance(resolved, expected_types):
            raise TypeError('%s requires types: %s and found %s' % (cls, expected_types, resolved))
          yield resolved

  def __init__(self, name, reinit_check=True):
    # This check prevents double-initialization in multiple-inheritance situations.
    # TODO(John Sirois): fix target inheritance - use super() to linearize or use alternatives to
    # multiple inheritance.
    if not reinit_check or not hasattr(self, '_initialized'):
      self.name = name
      self.description = None

      self.address = self.locate()

      # TODO(John Sirois): id is a builtin - use another name
      self.id = self._create_id()

      self.labels = set()
      self.register()
      self._initialized = True

      # For synthetic codegen targets this will be the original target from which
      # the target was synthesized.
      self.derived_from = self

  def _post_construct(self, func, *args, **kwargs):
    """Registers a command to invoke after this target's BUILD file is parsed."""

    ParseContext.locate().on_context_exit(func, *args, **kwargs)

  def _create_id(self):
    """Generates a unique identifer for the BUILD target.  The generated id is safe for use as a
    a path name on unix systems."""

    buildfile_relpath = os.path.dirname(self.address.buildfile.relpath)
    if buildfile_relpath in ('.', ''):
      return self.name
    else:
      return "%s.%s" % (buildfile_relpath.replace(os.sep, '.'), self.name)

  def locate(self):
    parse_context = ParseContext.locate()
    return Address(parse_context.buildfile, self.name)

  def register(self):
    existing = self._targets_by_address.get(self.address)
    if existing and existing.address.buildfile != self.address.buildfile:
      raise KeyError("%s defined in %s already defined in a sibling BUILD file: %s" % (
        self.address,
        self.address.buildfile.full_path,
        existing.address.buildfile.full_path,
      ))

    self._targets_by_address[self.address] = self
    self._addresses_by_buildfile[self.address.buildfile].add(self.address)

  def resolve(self):
    yield self

  def walk(self, work, predicate=None):
    """Performs a walk of this target's dependency graph visiting each node exactly once.  If a
    predicate is supplied it will be used to test each target before handing the target to work and
    descending.  Work can return targets in which case these will be added to the walk candidate set
    if not already walked."""

    self._walk(set(), work, predicate)

  def _walk(self, walked, work, predicate=None):
    for target in self.resolve():
      if target not in walked:
        walked.add(target)
        if not predicate or predicate(target):
          additional_targets = work(target)
          if hasattr(target, '_walk'):
            target._walk(walked, work, predicate)
          if additional_targets:
            for additional_target in additional_targets:
              if hasattr(additional_target, '_walk'):
                additional_target._walk(walked, work, predicate)

  # TODO(John Sirois): Kill this method once ant backend is gone
  @deprecated_with_warning("you're using deprecated pants commands, http://go/pantsmigration")
  def do_in_context(self, work):
    return ParseContext(self.address.buildfile).do_in_context(work)

  def with_description(self, description):
    self.description = description
    return self

  def add_labels(self, *label):
    self.labels.update(label)

  def remove_label(self, label):
    self.labels.remove(label)

  def has_label(self, label):
    return label in self.labels

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

Target._clear_all_addresses()
