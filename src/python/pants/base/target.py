# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import collections
from hashlib import sha1
import os

from twitter.common.lang import Compatibility

from pants.base.build_environment import get_buildroot
from pants.base.build_manual import manual
from pants.base.exceptions import TargetDefinitionException
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import hash_all
from pants.base.payload import EmptyPayload
from pants.base.source_root import SourceRoot
from pants.base.validation import assert_list


class AbstractTarget(object):
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

  @property
  def is_android(self):
    """Returns True if the target is an android target."""
    return self.has_label('android')


class Target(AbstractTarget):
  """The baseclass for all pants targets.

  Handles registration of a target amongst all parsed targets as well as location of the target
  parse context.
  """

  LANG_DISCRIMINATORS = {
    'java':   lambda t: t.is_jvm,
    'python': lambda t: t.is_python,
  }

  @classmethod
  def lang_discriminator(cls, lang):
    """Returns a tuple of target predicates that select the given lang vs all other supported langs.

       The left hand side accepts targets for the given language; the right hand side accepts
       targets for all other supported languages.
    """
    def is_other_lang(target):
      for name, discriminator in cls.LANG_DISCRIMINATORS.items():
        if name != lang and discriminator(target):
          return True
      return False
    return (cls.LANG_DISCRIMINATORS[lang], is_other_lang)

  @property
  def target_base(self):
    return SourceRoot.find(self)

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

  def __init__(self, name, address, build_graph, payload=None, exclusives=None):
    """
    :param string name: The target name.
    :param Address address: The Address that maps to this Target in the BuildGraph
    :param BuildGraph build_graph: The BuildGraph that this Target lives within
    """
    self.name = name
    self.address = address
    self.payload = payload or EmptyPayload()
    self._build_graph = build_graph
    self.description = None
    self.labels = set()
    self.declared_exclusives = collections.defaultdict(set)
    if exclusives is not None:
      for k in exclusives:
        self.declared_exclusives[k].add(exclusives[k])
    self.exclusives = None

    self._cached_fingerprint_map = {}
    self._cached_transitive_fingerprint_map = {}

  def assert_list(self, maybe_list, expected_type=Compatibility.string):
    return assert_list(maybe_list, expected_type, raise_type=lambda msg: TargetDefinitionException(self, msg))

  def compute_invalidation_hash(self, fingerprint_strategy=None):
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    return fingerprint_strategy.fingerprint_target(self)

  def invalidation_hash(self, fingerprint_strategy=None):
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    fp_name = fingerprint_strategy.name()
    if fp_name not in self._cached_fingerprint_map:
      self._cached_fingerprint_map[fp_name] = self.compute_invalidation_hash(fingerprint_strategy)
    return self._cached_fingerprint_map[fp_name]

  def mark_extra_invalidation_hash_dirty(self):
    pass

  def mark_invalidation_hash_dirty(self):
    self._cached_fingerprint_map = {}
    self._cached_transitive_fingerprint_map = {}
    self.mark_extra_invalidation_hash_dirty()

  def transitive_invalidation_hash(self, fingerprint_strategy=None):
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    fp_name = fingerprint_strategy.name()
    if fp_name not in self._cached_transitive_fingerprint_map:
      hasher = sha1()
      direct_deps = sorted(self.dependencies)
      for dep in direct_deps:
        hasher.update(dep.transitive_invalidation_hash(fingerprint_strategy))
      target_hash = self.invalidation_hash(fingerprint_strategy)
      dependencies_hash = hasher.hexdigest()[:12]
      combined_hash = '{target_hash}.{deps_hash}'.format(target_hash=target_hash,
                                                         deps_hash=dependencies_hash)
      self._cached_transitive_fingerprint_map[fp_name] = combined_hash
    return self._cached_transitive_fingerprint_map[fp_name]

  def mark_transitive_invalidation_hash_dirty(self):
    self._cached_transitive_fingerprint_map = {}
    self.mark_extra_transitive_invalidation_hash_dirty()

  def mark_extra_transitive_invalidation_hash_dirty(self):
    pass

  def inject_dependency(self, dependency_address):
    self._build_graph.inject_dependency(dependent=self.address, dependency=dependency_address)
    def invalidate_dependee(dependee):
      dependee.mark_transitive_invalidation_hash_dirty()
    self._build_graph.walk_transitive_dependee_graph([self.address], work=invalidate_dependee)

  def has_sources(self, extension=''):
    return self.payload.has_sources(extension)

  def sources_relative_to_buildroot(self):
    if self.has_sources():
      return self.payload.sources_relative_to_buildroot()
    else:
      return []

  def sources_relative_to_source_root(self):
    if self.has_sources():
      abs_source_root = os.path.join(get_buildroot(), self.target_base)
      for source in self.sources_relative_to_buildroot():
        abs_source = os.path.join(get_buildroot(), source)
        yield os.path.relpath(abs_source, abs_source_root)

  @property
  def derived_from(self):
    """Returns the target this target was derived from.

    If this target was not derived from another, returns itself.
    """
    return self._build_graph.get_derived_from(self.address)

  @property
  def concrete_derived_from(self):
    """Returns the concrete target this target was (directly or indirectly) derived from.

    The returned target is guaranteed to not have been derived from any other target, and is thus
    guaranteed to be a 'real' target from a BUILD file, not a programmatically injected target.
    """
    return self._build_graph.get_concrete_derived_from(self.address)

  @property
  def traversable_specs(self):
    return []

  @property
  def traversable_dependency_specs(self):
    return []

  @property
  def dependencies(self):
    return [self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependencies_of(self.address)]

  @property
  def dependents(self):
    return [self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependents_of(self.address)]

  @property
  def is_synthetic(self):
    return self.address.is_synthetic

  @property
  def is_original(self):
    """Returns ``True`` if this target is derived from no other."""
    return self.derived_from == self

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
    self.add_to_exclusives(target.declared_exclusives)
    return None

  def add_to_exclusives(self, exclusives):
    if exclusives is not None:
      for key in exclusives:
        self.exclusives[key] |= exclusives[key]

  @property
  def id(self):
    """A unique identifier for the Target.

    The generated id is safe for use as a path name on unix systems.
    """
    return self.address.path_safe_spec

  @property
  def identifier(self):
    """A unique identifier for the Target.

    The generated id is safe for use as a path name on unix systems.
    """
    return self.id

  def walk(self, work, predicate=None):
    """Walk of this target's dependency graph, in DFS order, visiting each node exactly once.

    If a predicate is supplied it will be used to test each target before handing the target to
    work and descending. Work can return targets in which case these will be added to the walk
    candidate set if not already walked.

    :param work: Callable that takes a :py:class:`pants.base.target.Target`
      as its single argument.
    :param predicate: Callable that takes a :py:class:`pants.base.target.Target`
      as its single argument and returns True if the target should passed to ``work``.
    """
    if not callable(work):
      raise ValueError('work must be callable but was %s' % work)
    if predicate and not callable(predicate):
      raise ValueError('predicate must be callable but was %s' % predicate)
    self._build_graph.walk_transitive_dependency_graph([self.address], work, predicate)

  def closure(self):
    """Returns this target's transitive dependencies, in DFS order."""
    return self._build_graph.transitive_subgraph_of_addresses([self.address])

  @manual.builddict()
  def with_description(self, description):
    """Set a human-readable description of this target.

    :param description: Descriptive string"""
    self.description = description
    return self

  def add_labels(self, *label):
    self.labels.update(label)

  def remove_label(self, label):
    self.labels.remove(label)

  def has_label(self, label):
    return label in self.labels

  def __lt__(self, other):
    return self.address < other.address

  def __eq__(self, other):
    return isinstance(other, Target) and self.address == other.address

  def __hash__(self):
    return hash(self.address)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    addr = self.address if hasattr(self, 'address') else 'address not yet set'
    return "%s(%s)" % (type(self).__name__, addr)
