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

from __future__ import print_function

import collections
import os
import sys

from twitter.common.collections import OrderedSet, maybe_list
from twitter.common.lang import Compatibility

from .address import Address
from .build_manual import manual
from .hash_utils import hash_all
from .parse_context import ParseContext


class TargetDefinitionException(Exception):
  """Thrown on errors in target definitions."""

  def __init__(self, target, msg):
    address = getattr(target, 'address', None)
    if address is None:
      try:
        location = ParseContext.locate().current_buildfile
      except ParseContext.ContextError:
        location = 'unknown location'
      address = 'unknown target of type %s in %s' % (target.__class__.__name__, location)
    super(Exception, self).__init__('Error with %s: %s' % (address, msg))


class AbstractTarget(object):

  @property
  def is_concrete(self):
    """Returns true if a target resolves to itself."""
    targets = list(self.resolve())
    return len(targets) == 1 and targets[0] == self

  @property
  def has_resources(self):
    """Returns True if the target has an associated set of Resources."""
    return hasattr(self, 'resources') and self.resources

  @property
  def is_exported(self):
    """Returns True if the target provides an artifact exportable from the repo."""
    # TODO(John Sirois): fixup predicate dipping down into details here.
    return self.has_label('exportable') and self.provides

  @property
  def is_internal(self):
    """Returns True if the target is internal to the repo (ie: it might have dependencies)."""
    return self.has_label('internal')

  @property
  def is_jar(self):
    """Returns True if the target is a jar."""
    return False

  @property
  def is_java_agent(self):
    """Returns `True` if the target is a java agent."""
    return self.has_label('java_agent')

  @property
  def is_jvm_app(self):
    """Returns True if the target produces a java application with bundled auxiliary files."""
    return False

  @property
  def is_thrift(self):
    """Returns True if the target has thrift IDL sources."""
    return False

  @property
  def is_jvm(self):
    """Returns True if the target produces jvm bytecode."""
    return self.has_label('jvm')

  @property
  def is_codegen(self):
    """Returns True if the target is a codegen target."""
    return self.has_label('codegen')

  @property
  def is_synthetic(self):
    """Returns True if the target is a synthetic target injected by the runtime."""
    return self.has_label('synthetic')

  @property
  def is_jar_library(self):
    """Returns True if the target is an external jar library."""
    return self.has_label('jars')

  @property
  def is_java(self):
    """Returns True if the target has or generates java sources."""
    return self.has_label('java')

  @property
  def is_apt(self):
    """Returns True if the target exports an annotation processor."""
    return self.has_label('apt')

  @property
  def is_python(self):
    """Returns True if the target has python sources."""
    return self.has_label('python')

  @property
  def is_scala(self):
    """Returns True if the target has scala sources."""
    return self.has_label('scala')

  @property
  def is_scalac_plugin(self):
    """Returns True if the target builds a scalac plugin."""
    return self.has_label('scalac_plugin')

  @property
  def is_test(self):
    """Returns True if the target is comprised of tests."""
    return self.has_label('tests')

  def resolve(self):
    """Returns an iterator over the target(s) this target represents."""
    yield self


@manual.builddict()
class Target(AbstractTarget):
  """The baseclass for all pants targets.

  Handles registration of a target amongst all parsed targets as well as location of the target
  parse context.
  """

  _targets_by_address = None
  _addresses_by_buildfile = None

  @classmethod
  def identify(cls, targets):
    """Generates an id for a set of targets."""
    return cls.combine_ids(target.id for target in targets)

  @classmethod
  def maybe_readable_identify(cls, targets):
    """Generates an id for a set of targets.

    If the set is a single target, just use that target's id."""
    return cls.maybe_readable_combine_ids([target.id for target in targets])

  @staticmethod
  def combine_ids(ids):
    """Generates a combined id for a set of ids."""
    return hash_all(sorted(ids))  # We sort so that the id isn't sensitive to order.

  @classmethod
  def maybe_readable_combine_ids(cls, ids):
    """Generates combined id for a set of ids, but if the set is a single id, just use that."""
    ids = list(ids)  # We can't len a generator.
    return ids[0] if len(ids) == 1 else cls.combine_ids(ids)

  @classmethod
  def get_all_addresses(cls, buildfile):
    """Returns all of the target addresses in the specified buildfile if already parsed; otherwise,
    parses the buildfile to find all the addresses it contains and then returns them.
    """
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
    context of its parent directory and returns the parsed target.
    """
    def lookup():
      return cls._targets_by_address.get(address, None)

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
        concrete_targets = [t for t in target.resolve() if t.is_concrete]
        for resolved in concrete_targets:
          if expected_types and not isinstance(resolved, expected_types):
            raise TypeError('%s requires types: %s and found %s' % (cls, expected_types, resolved))
          yield resolved

  def __init__(self, name, reinit_check=True, exclusives=None):
    """
    :param string name: The target name.
    """
    # See "get_all_exclusives" below for an explanation of the exclusives parameter.
    # This check prevents double-initialization in multiple-inheritance situations.
    # TODO(John Sirois): fix target inheritance - use super() to linearize or use alternatives to
    # multiple inheritance.
    if not reinit_check or not hasattr(self, '_initialized'):
      if not isinstance(name, Compatibility.string):
        self.address = '%s:%s' % (ParseContext.locate().current_buildfile, str(name))
        raise TargetDefinitionException(self, "Invalid target name: %s" % name)
      self.name = name
      self.description = None

      self.address = self._locate()

      # TODO(John Sirois): Transition all references to self.identifier to eliminate id builtin
      # ambiguity
      self.id = self._create_id()

      self._register()

      self.labels = set()

      self._initialized = True

      self.declared_exclusives = collections.defaultdict(set)
      if exclusives is not None:
        for k in exclusives:
          self.declared_exclusives[k].add(exclusives[k])
      self.exclusives = None

      # For synthetic codegen targets this will be the original target from which
      # the target was synthesized.
      self._derived_from = self

  @property
  def derived_from(self):
    """Returns the target this target was derived from.

    If this target was not derived from another, returns itself.
    """
    return self._derived_from

  @derived_from.setter
  def derived_from(self, value):
    """Sets the target this target was derived from.

    Various tasks may create targets not written down in any BUILD file.  Often these targets are
    derived from targets written down in BUILD files though in which case the derivation chain
    should be maintained.
    """
    if value and not isinstance(value, AbstractTarget):
      raise ValueError('Expected derived_from to be a Target, given %s of type %s'
                       % (value, type(value)))
    self._derived_from = value

  def get_declared_exclusives(self):
    return self.declared_exclusives

  def add_to_exclusives(self, exclusives):
    if exclusives is not None:
      for key in exclusives:
        self.exclusives[key] |= exclusives[key]

  def get_all_exclusives(self):
    """ Get a map of all exclusives declarations in the transitive dependency graph.

    For a detailed description of the purpose and use of exclusives tags,
    see the documentation of the CheckExclusives task.

    """
    if self.exclusives is None:
      self._propagate_exclusives()
    return self.exclusives

  def _propagate_exclusives(self):
    if self.exclusives is None:
      self.exclusives = collections.defaultdict(set)
      self.add_to_exclusives(self.declared_exclusives)
      # This may perform more work than necessary.
      # We want to just traverse the immediate dependencies of this target,
      # but for a general target, we can't do that. _propagate_exclusives is overridden
      # in subclasses when possible to avoid the extra work.
      self.walk(lambda t: self._propagate_exclusives_work(t))

  def _propagate_exclusives_work(self, target):
    # Note: this will cause a stack overflow if there is a cycle in
    # the dependency graph, so exclusives checking should occur after
    # cycle detection.
    if hasattr(target, "declared_exclusives"):
      self.add_to_exclusives(target.declared_exclusives)
    return None

  def _post_construct(self, func, *args, **kwargs):
    """Registers a command to invoke after this target's BUILD file is parsed."""
    ParseContext.locate().on_context_exit(func, *args, **kwargs)

  def _create_id(self):
    """Generates a unique identifier for the BUILD target.

    The generated id is safe for use as a path name on unix systems.
    """
    buildfile_relpath = os.path.dirname(self.address.buildfile.relpath)
    if buildfile_relpath in ('.', ''):
      return self.name
    else:
      return "%s.%s" % (buildfile_relpath.replace(os.sep, '.'), self.name)

  def _locate(self):
    parse_context = ParseContext.locate()
    return Address(parse_context.current_buildfile, self.name)

  def _register(self):
    existing = self._targets_by_address.get(self.address)
    if existing and existing is not self:
      if existing.address.buildfile != self.address.buildfile:
        raise TargetDefinitionException(self, "already defined in a sibling BUILD "
                                              "file: %s" % existing.address.buildfile.relpath)
      else:
        raise TargetDefinitionException(self, "duplicate to %s" % existing)

    self._targets_by_address[self.address] = self
    self._addresses_by_buildfile[self.address.buildfile].add(self.address)

  @property
  def identifier(self):
    """A unique identifier for the BUILD target.

    The generated id is safe for use as a path name on unix systems.
    """
    return self.id

  def walk(self, work, predicate=None):
    """Walk of this target's dependency graph visiting each node exactly once.

    If a predicate is supplied it will be used to test each target before handing the target to
    work and descending. Work can return targets in which case these will be added to the walk
    candidate set if not already walked.

    :param work: Callable that takes a :py:class:`twitter.pants.base.target.Target`
      as its single argument.
    :param predicate: Callable that takes a :py:class:`twitter.pants.base.target.Target`
      as its single argument and returns True if the target should passed to ``work``.
    """
    if not callable(work):
      raise ValueError('work must be callable but was %s' % work)
    if predicate and not callable(predicate):
      raise ValueError('predicate must be callable but was %s' % predicate)
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

  @manual.builddict()
  def with_description(self, description):
    """Set a human-readable description of this target."""
    self.description = description
    return self

  def add_labels(self, *label):
    self.labels.update(label)

  def remove_label(self, label):
    self.labels.remove(label)

  def has_label(self, label):
    return label in self.labels

  def __eq__(self, other):
    return isinstance(other, Target) and self.address == other.address

  def __hash__(self):
    return hash(self.address)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s(%s)" % (type(self).__name__, self.address)

  @staticmethod
  def has_jvm_targets(targets):
    """Returns true if the given sequence of targets contains at least one jvm target as determined
    by is_jvm(...)
    """

    return len(list(Target.extract_jvm_targets(targets))) > 0

  @staticmethod
  def extract_jvm_targets(targets):
    """Returns an iterator over the jvm targets the given sequence of targets resolve to.  The
    given targets can be a mix of types and only valid jvm targets (as determined by is_jvm(...)
    will be returned by the iterator.
    """

    for target in targets:
      if target is None:
        print('Warning! Null target!', file=sys.stderr)
        continue
      for real_target in target.resolve():
        if real_target.is_jvm:
          yield real_target

  def has_sources(self, extension=None):
    """Returns True if the target has sources.

    If an extension is supplied the target is further checked for at least 1 source with the given
    extension.
    """
    return (self.has_label('sources') and
            (not extension or
             (hasattr(self, 'sources') and
              any(source.endswith(extension) for source in self.sources))))


Target._clear_all_addresses()
