# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from six import string_types

from pants.backend.core.wrapped_globs import FilesetWithSpec
from pants.base.address import Addresses, SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import hash_all
from pants.base.payload import Payload
from pants.base.payload_field import DeferredSourcesField, SourcesField
from pants.base.source_root import SourceRoot
from pants.base.target_addressable import TargetAddressable
from pants.base.validation import assert_list


class AbstractTarget(object):

  @classmethod
  def subsystems(cls):
    """The subsystems this target uses.

    Targets always use the global subsystem instance. They have no notion of any other scope.

    :return: A tuple of subsystem types.
    """
    return tuple()

  @property
  def has_resources(self):
    """Returns True if the target has an associated set of Resources."""
    return hasattr(self, 'resources') and self.resources

  @property
  def is_exported(self):
    """Returns True if the target provides an artifact exportable from the repo."""
    # TODO(John Sirois): fixup predicate dipping down into details here.
    return self.has_label('exportable') and self.provides

  # DEPRECATED  to be removed after 0.0.29
  # do not use this method, use  isinstance(..., JavaThriftLibrary) or a yet-to-be-defined mixin
  @property
  def is_thrift(self):
    """Returns True if the target has thrift IDL sources."""
    return False

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_jvm(self):
    """Returns True if the target produces jvm bytecode."""
    return self.has_label('jvm')

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_codegen(self):
    """Returns True if the target is a codegen target."""
    return self.has_label('codegen')

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_java(self):
    """Returns True if the target has or generates java sources."""
    return self.has_label('java')

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_python(self):
    """Returns True if the target has python sources."""
    return self.has_label('python')

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_scala(self):
    """Returns True if the target has scala sources."""
    return self.has_label('scala')

  # DEPRECATED to be removed after 0.0.29
  #  do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_scalac_plugin(self):
    """Returns True if the target builds a scalac plugin."""
    return self.has_label('scalac_plugin')

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_test(self):
    """Returns True if the target is comprised of tests."""
    return self.has_label('tests')

  # DEPRECATED to be removed after 0.0.29
  # do not use this method, use an isinstance check on a yet-to-be-defined mixin
  @property
  def is_android(self):
    """Returns True if the target is an android target."""
    return self.has_label('android')


class Target(AbstractTarget):
  """The baseclass for all pants targets.

  Handles registration of a target amongst all parsed targets as well as location of the target
  parse context.
  """

  class WrongNumberOfAddresses(Exception):
    """Internal error, too many elements in Addresses"""

  class UnknownArguments(TargetDefinitionException):
    """Unknown keyword arguments supplied to Target."""

  class IllegalArgument(TargetDefinitionException):
    """Argument that isn't allowed supplied to Target."""

  LANG_DISCRIMINATORS = {
    'java': lambda t: t.is_jvm,
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

  @classmethod
  def get_addressable_type(target_cls):
    class ConcreteTargetAddressable(TargetAddressable):

      @classmethod
      def get_target_type(cls):
        return target_cls
    return ConcreteTargetAddressable

  @property
  def target_base(self):
    """:returns: the source root path for this target."""
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

  def __init__(self, name, address, build_graph, payload=None, tags=None, description=None,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target address.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param Address address: The Address that maps to this Target in the BuildGraph
    :param BuildGraph build_graph: The BuildGraph that this Target lives within
    :param Payload payload: The configuration encapsulated by this target.  Also in charge of
      most fingerprinting details.
    :param iterable<string> tags: Arbitrary string tags that describe this target. Usable
        by downstream/custom tasks for reasoning about build graph. NOT included in payloads
        and thus not used in fingerprinting, thus not suitable for anything that affects how
        a particular target is built.
    :param string description: Human-readable description of this target.
    """
    # dependencies is listed above; implementation hides in TargetAddressable
    self.payload = payload or Payload()
    self.payload.freeze()
    self.name = name
    self.address = address
    self._tags = set(tags or [])
    self._build_graph = build_graph
    self.description = description
    self.labels = set()

    self._cached_fingerprint_map = {}
    self._cached_transitive_fingerprint_map = {}

    if kwargs:
      error_message = '{target_type} received unknown arguments: {args}'
      raise self.UnknownArguments(address.spec, error_message.format(
        target_type=type(self).__name__,
        args=''.join('\n  {} = {}'.format(key, value) for key, value in kwargs.items())
      ))

  @property
  def tags(self):
    return self._tags

  @property
  def num_chunking_units(self):
    return max(1, len(self.sources_relative_to_buildroot()))

  def assert_list(self, maybe_list, expected_type=string_types, key_arg=None):
    return assert_list(maybe_list, expected_type, key_arg=key_arg,
                       raise_type=lambda msg: TargetDefinitionException(self, msg))

  def compute_invalidation_hash(self, fingerprint_strategy=None):
    """
     :param FingerprintStrategy fingerprint_strategy: optional fingerprint strategy to use to compute
    the fingerprint of a target
    :return: a fingerprint representing this target (no dependencies)
    :rtype: string
    """
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    return fingerprint_strategy.fingerprint_target(self)

  def invalidation_hash(self, fingerprint_strategy=None):
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    if fingerprint_strategy not in self._cached_fingerprint_map:
      self._cached_fingerprint_map[fingerprint_strategy] = self.compute_invalidation_hash(fingerprint_strategy)
    return self._cached_fingerprint_map[fingerprint_strategy]

  def mark_extra_invalidation_hash_dirty(self):
    pass

  def mark_invalidation_hash_dirty(self):
    self._cached_fingerprint_map = {}
    self._cached_transitive_fingerprint_map = {}
    self.mark_extra_invalidation_hash_dirty()

  def transitive_invalidation_hash(self, fingerprint_strategy=None):
    """
    :param FingerprintStrategy fingerprint_strategy: optional fingerprint strategy to use to compute
    the fingerprint of a target
    :return: A fingerprint representing this target and all of its dependencies.
      The return value can be `None`, indicating that this target and all of its transitive dependencies
      did not contribute to the fingerprint, according to the provided FingerprintStrategy.
    :rtype: string
    """
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    if fingerprint_strategy not in self._cached_transitive_fingerprint_map:
      hasher = sha1()

      def dep_hash_iter():
        for dep in self.dependencies:
          dep_hash = dep.transitive_invalidation_hash(fingerprint_strategy)
          if dep_hash is not None:
            yield dep_hash
      dep_hashes = sorted(list(dep_hash_iter()))
      for dep_hash in dep_hashes:
        hasher.update(dep_hash)
      target_hash = self.invalidation_hash(fingerprint_strategy)
      if target_hash is None and not dep_hashes:
        return None
      dependencies_hash = hasher.hexdigest()[:12]
      combined_hash = '{target_hash}.{deps_hash}'.format(target_hash=target_hash,
                                                         deps_hash=dependencies_hash)
      self._cached_transitive_fingerprint_map[fingerprint_strategy] = combined_hash
    return self._cached_transitive_fingerprint_map[fingerprint_strategy]

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
    """
    :param string extension: suffix of filenames to test for
    :return: True if the target contains sources that match the optional extension suffix
    :rtype: bool
    """
    sources_field = self.payload.get_field('sources')
    if sources_field:
      return sources_field.has_sources(extension)
    else:
      return False

  def sources_relative_to_buildroot(self):
    if self.has_sources():
      return self.payload.sources.relative_to_buildroot()
    else:
      return []

  def sources_relative_to_source_root(self):
    if self.has_sources():
      abs_source_root = os.path.join(get_buildroot(), self.target_base)
      for source in self.sources_relative_to_buildroot():
        abs_source = os.path.join(get_buildroot(), source)
        yield os.path.relpath(abs_source, abs_source_root)

  def globs_relative_to_buildroot(self):
    sources_field = self.payload.get_field('sources')
    if sources_field:
      return sources_field.filespec

  @property
  def derived_from(self):
    """Returns the target this target was derived from.

    If this target was not derived from another, returns itself.
    """
    return self._build_graph.get_derived_from(self.address)

  @property
  def derived_from_chain(self):
    """Returns all targets that this target was derived from.

    If this target was not derived from another, returns an empty sequence.
    """
    cur = self
    while cur.derived_from is not cur:
      cur = cur.derived_from
      yield cur

  @property
  def concrete_derived_from(self):
    """Returns the concrete target this target was (directly or indirectly) derived from.

    The returned target is guaranteed to not have been derived from any other target, and is thus
    guaranteed to be a 'real' target from a BUILD file, not a programmatically injected target.
    """
    return self._build_graph.get_concrete_derived_from(self.address)

  @property
  def traversable_specs(self):
    """
    :return: specs referenced by this target to be injected into the build graph
    :rtype: list of strings
    """
    return []

  @property
  def traversable_dependency_specs(self):
    """
    :return: specs representing dependencies of this target that will be injected to the build
    graph and linked in the graph as dependencies of this target
    :rtype: list of strings
    """
    # To support DeferredSourcesField
    for name, payload_field in self.payload.fields:
      if isinstance(payload_field, DeferredSourcesField) and payload_field.address:
        yield payload_field.address.spec

  @property
  def dependencies(self):
    """
    :return: targets that this target depends on
    :rtype: list of Target
    """
    return [self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependencies_of(self.address)]

  @property
  def dependents(self):
    """
    :return: targets that depend on this target
    :rtype: list of Target
    """
    return [self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependents_of(self.address)]

  @property
  def is_synthetic(self):
    """
    :return: True if this target did not originate from a BUILD file.
    """
    return self.concrete_derived_from.address != self.address

  @property
  def is_original(self):
    """Returns ``True`` if this target is derived from no other."""
    return self.derived_from == self

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
    """Walk of this target's dependency graph, DFS preorder traversal, visiting each node exactly
    once.

    If a predicate is supplied it will be used to test each target before handing the target to
    work and descending. Work can return targets in which case these will be added to the walk
    candidate set if not already walked.

    :param work: Callable that takes a :py:class:`pants.base.target.Target`
      as its single argument.
    :param predicate: Callable that takes a :py:class:`pants.base.target.Target`
      as its single argument and returns True if the target should passed to ``work``.
    """
    if not callable(work):
      raise ValueError('work must be callable but was {}'.format(work))
    if predicate and not callable(predicate):
      raise ValueError('predicate must be callable but was {}'.format(predicate))
    self._build_graph.walk_transitive_dependency_graph([self.address], work, predicate)

  def closure(self, bfs=False):
    """Returns this target's transitive dependencies.

    The walk will be depth-first in preorder, or breadth first if bfs=True is specified.
    """
    if bfs:
      return self._build_graph.transitive_subgraph_of_addresses_bfs([self.address])
    else:
      return self._build_graph.transitive_subgraph_of_addresses([self.address])

  # TODO(Eric Ayers) As of 2/5/2015 this call is DEPRECATED and should be removed soon
  def add_labels(self, *label):
    self.labels.update(label)

  # TODO(Eric Ayers) As of 2/5/2015 this call is DEPRECATED and should be removed soon
  def remove_label(self, label):
    self.labels.remove(label)

  # TODO(Eric Ayers) As of 2/5/2015 this call is DEPRECATED and should be removed soon
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
    return "{}({})".format(type(self).__name__, addr)

  def create_sources_field(self, sources, sources_rel_path, address=None, key_arg=None):
    """Factory method to create a SourcesField appropriate for the type of the sources object.

    Note that this method is called before the call to Target.__init__ so don't expect fields to
    be populated!
    :return: a payload field object representing the sources parameter
    :rtype: SourcesField
    """

    if isinstance(sources, Addresses):
      # Currently, this is only created by the result of from_target() which takes a single argument
      if len(sources.addresses) != 1:
        raise self.WrongNumberOfAddresses(
          "Expected a single address to from_target() as argument to {spec}"
          .format(spec=address.spec))
      referenced_address = SyntheticAddress.parse(sources.addresses[0],
                                                  relative_to=sources.rel_path)
      return DeferredSourcesField(ref_address=referenced_address)
    elif isinstance(sources, FilesetWithSpec):
      filespec = sources.filespec
    else:
      sources = sources or []
      assert_list(sources, key_arg=key_arg)
      filespec = {'globs': [os.path.join(sources_rel_path, src) for src in (sources or [])]}

    return SourcesField(sources=sources, sources_rel_path=sources_rel_path, filespec=filespec)
