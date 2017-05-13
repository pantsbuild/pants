# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from hashlib import sha1

from six import string_types
from twitter.common.collections import OrderedSet, maybe_list

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated
from pants.base.exceptions import TargetDefinitionException
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import hash_all
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.validation import assert_list
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.target_addressable import TargetAddressable
from pants.build_graph.target_scopes import Scope
from pants.source.payload_fields import SourcesField
from pants.source.wrapped_globs import Files, FilesetWithSpec, Globs
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class AbstractTarget(object):

  @classmethod
  def subsystems(cls):
    """The subsystems this target uses.

    Targets always use the global subsystem instance. They have no notion of any other scope.

    :API: public

    :return: A tuple of subsystem types.
    """
    return tuple()

  @classmethod
  def alias(cls):
    """Subclasses should return their desired BUILD file alias.

    :rtype: string
    """
    raise NotImplementedError()

  # TODO: Kill this in 1.5.0.dev0, once this old-style resource specification is gone.
  @property
  def has_resources(self):
    """Returns True if the target has an associated set of Resources.

    :API: public
    """
    return hasattr(self, 'resources') and self.resources

  @property
  def is_exported(self):
    """Returns True if the target provides an artifact exportable from the repo.

    :API: public
    """
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


class Target(AbstractTarget):
  """A generic target used to group dependencies.

  The baseclass for all pants targets.

  Handles registration of a target amongst all parsed targets as well as location of the target
  parse context.

  :API: public
  """

  class RecursiveDepthError(AddressLookupError):
    """Raised when there are too many recursive calls to calculate the fingerprint."""

  _MAX_RECURSION_DEPTH = 250

  class WrongNumberOfAddresses(Exception):
    """Internal error, too many elements in Addresses

    :API: public
    """

  class IllegalArgument(TargetDefinitionException):
    """Argument that isn't allowed supplied to Target.

    :API: public
    """

  class Arguments(Subsystem):
    """Options relating to handling target arguments."""

    class UnknownArgumentError(TargetDefinitionException):
      """An unknown keyword argument was supplied to Target."""

    options_scope = 'target-arguments'

    @classmethod
    def register_options(cls, register):
      register('--ignored', advanced=True, type=dict,
               help='Map of target name to a list of keyword arguments that should be ignored if a '
                    'target receives them unexpectedly. Typically used to allow usage of arguments '
                    'in BUILD files that are not yet available in the current version of pants.')
      register('--implicit-sources', advanced=True, type=bool,
               help='If True, Pants will infer the value of the sources argument for certain '
                    'target types, if they do not have explicit sources specified.')

    @classmethod
    def check(cls, target, kwargs):
      """
      :API: public
      """
      cls.global_instance().check_unknown(target, kwargs)

    def check_unknown(self, target, kwargs):
      """
      :API: public
      """
      ignore_params = set((self.get_options().ignored or {}).get(target.type_alias, ()))
      unknown_args = {arg: value for arg, value in kwargs.items() if arg not in ignore_params}
      ignored_args = {arg: value for arg, value in kwargs.items() if arg in ignore_params}
      if ignored_args:
        logger.debug('{target} ignoring the unimplemented arguments: {args}'
                     .format(target=target.address.spec,
                             args=', '.join('{} = {}'.format(key, val)
                                            for key, val in ignored_args.items())))
      if unknown_args:
        error_message = '{target_type} received unknown arguments: {args}'
        raise self.UnknownArgumentError(target.address.spec, error_message.format(
          target_type=type(target).__name__,
          args=''.join('\n  {} = {}'.format(key, value) for key, value in unknown_args.items())
        ))

  @classmethod
  def subsystems(cls):
    return super(Target, cls).subsystems() + (cls.Arguments,)

  @classmethod
  def get_addressable_type(target_cls):
    """
    :API: public
    """
    class ConcreteTargetAddressable(TargetAddressable):

      @classmethod
      def get_target_type(cls):
        return target_cls
    return ConcreteTargetAddressable

  @memoized_property
  def target_base(self):
    """
    :API: public

    :returns: the source root path for this target.
    """
    source_root = self._sources_field.source_root
    if not source_root:
      raise TargetDefinitionException(self, 'Not under any configured source root.')
    return source_root.path

  @classmethod
  def identify(cls, targets):
    """Generates an id for a set of targets.

    :API: public
    """
    return cls.combine_ids(target.id for target in targets)

  @classmethod
  def maybe_readable_identify(cls, targets):
    """Generates an id for a set of targets.

    If the set is a single target, just use that target's id.

    :API: public
    """
    return cls.maybe_readable_combine_ids([target.id for target in targets])

  @classmethod
  def compute_target_id(cls, address):
    """Computes a target id from the given address."""
    id_candidate = address.path_safe_spec
    if len(id_candidate) >= 200:
      # two dots + 79 char head + 79 char tail + 40 char sha1
      return '{}.{}.{}'.format(id_candidate[:79], sha1(id_candidate).hexdigest(), id_candidate[-79:])
    return id_candidate

  @staticmethod
  def combine_ids(ids):
    """Generates a combined id for a set of ids.

    :API: public
    """
    return hash_all(sorted(ids))  # We sort so that the id isn't sensitive to order.

  @classmethod
  def maybe_readable_combine_ids(cls, ids):
    """Generates combined id for a set of ids, but if the set is a single id, just use that.

    :API: public
    """
    ids = list(ids)  # We can't len a generator.
    return ids[0] if len(ids) == 1 else cls.combine_ids(ids)

  @classmethod
  def _closure_predicate(cls, include_scopes=None, exclude_scopes=None, respect_intransitive=False):
    if not respect_intransitive and include_scopes is None and exclude_scopes is None:
      return None
    def predicate(target, level):
      if not target.scope.in_scope(include_scopes=include_scopes, exclude_scopes=exclude_scopes):
        return False
      if respect_intransitive and not target.transitive and level > 0:
        return False
      return True
    return predicate

  @classmethod
  def closure_for_targets(cls, target_roots, exclude_scopes=None, include_scopes=None,
                          bfs=None, postorder=None, respect_intransitive=False):
    """Computes the closure of the given targets respecting the given input scopes.

    :API: public

    :param list target_roots: The list of Targets to start from. These targets will always be
      included in the closure, regardless of scope settings.
    :param Scope exclude_scopes: If present and non-empty, only dependencies which have none of the
      scope names in this Scope will be traversed.
    :param Scope include_scopes: If present and non-empty, only dependencies which have at least one
      of the scope names in this Scope will be traversed.
    :param bool bfs: Whether to traverse in breadth-first or depth-first order. (Defaults to True).
    :param bool respect_intransitive: If True, any dependencies which have the 'intransitive' scope
      will not be included unless they are direct dependencies of one of the root targets. (Defaults
      to False).
    """
    target_roots = list(target_roots) # Sometimes generators are passed into this function.
    if not target_roots:
      return OrderedSet()

    build_graph = target_roots[0]._build_graph
    addresses = [target.address for target in target_roots]
    leveled_predicate = cls._closure_predicate(include_scopes=include_scopes,
                                               exclude_scopes=exclude_scopes,
                                               respect_intransitive=respect_intransitive)
    closure = OrderedSet()

    if not bfs:
      build_graph.walk_transitive_dependency_graph(
        addresses=addresses,
        work=closure.add,
        postorder=postorder,
        leveled_predicate=leveled_predicate,
      )
    else:
      closure.update(build_graph.transitive_subgraph_of_addresses_bfs(
        addresses=addresses,
        leveled_predicate=leveled_predicate,
      ))

    # Make sure all the roots made it into the closure.
    closure.update(target_roots)
    return closure

  def __init__(self, name, address, build_graph, type_alias=None, payload=None, tags=None,
               description=None, no_cache=False, scope=None, _transitive=None,
               **kwargs):
    """
    :API: public

    :param string name: The name of this target, which combined with this build file defines the
                        target address.
    :param dependencies: Target address specs of other targets that this target depends on.
    :type dependencies: list of strings
    :param address: The Address that maps to this Target in the BuildGraph.
    :type address: :class:`pants.build_graph.address.Address`
    :param build_graph: The BuildGraph that this Target lives within.
    :type build_graph: :class:`pants.build_graph.build_graph.BuildGraph`
    :param string type_alias: The type_alias used to construct this target, may be None if
                              constructed directly.
    :param payload: The configuration encapsulated by this target.  Also in charge of most
                    fingerprinting details.
    :type payload: :class:`pants.base.payload.Payload`
    :param tags: Arbitrary string tags that describe this target. Usable by downstream/custom tasks
                 for reasoning about the build graph. NOT included in payloads and thus not used in
                 fingerprinting, thus not suitable for anything that affects how a particular
                 target is built.
    :type tags: :class:`collections.Iterable` of strings
    :param no_cache: If True, results for this target should not be stored in the artifact cache.
    :param string description: Human-readable description of this target.
    :param string scope: The scope of this target, used to determine its inclusion on the classpath
      (and possibly more things in the future). See :class:`pants.build_graph.target_scopes.Scopes`.
      A value of None, '', or 'default' results in the default scope, which is included everywhere.
    """
    # NB: dependencies are in the pydoc above as a BUILD dictionary hack only; implementation hides
    # the dependencies via TargetAddressable.

    self.payload = payload or Payload()
    self._scope = Scope(scope)
    self.payload.add_field('scope_string', PrimitiveField(str(scope)))
    self.payload.add_field('transitive',
                           PrimitiveField(True if _transitive is None else _transitive))
    self.payload.freeze()
    self.name = name
    self.address = address
    self._build_graph = build_graph
    self._type_alias = type_alias
    self._tags = set(tags or [])
    self.description = description
    self.labels = set()

    self._cached_fingerprint_map = {}
    self._cached_all_transitive_fingerprint_map = {}
    self._cached_direct_transitive_fingerprint_map = {}
    if no_cache:
      self.add_labels('no_cache')
    if kwargs:
      self.Arguments.check(self, kwargs)

  @property
  def scope(self):
    return self._scope

  @property
  def transitive(self):
    return self.payload.transitive

  @property
  def type_alias(self):
    """Returns the type alias this target was constructed via.

    For a target read from a BUILD file, this will be target alias, like 'java_library'.
    For a target constructed in memory, this will be the simple class name, like 'JavaLibrary'.

    The end result is that the type alias should be the most natural way to refer to this target's
    type to the author of the target instance.

    :API: public

    :rtype: string
    """
    return self._type_alias or type(self).__name__

  @property
  def tags(self):
    """
    :API: public
    """
    return self._tags

  def assert_list(self, putative_list, expected_type=string_types, key_arg=None):
    """
    :API: public
    """
    return assert_list(putative_list, expected_type, key_arg=key_arg,
                       raise_type=lambda msg: TargetDefinitionException(self, msg))

  def compute_invalidation_hash(self, fingerprint_strategy=None):
    """
    :API: public

     :param FingerprintStrategy fingerprint_strategy: optional fingerprint strategy to use to compute
    the fingerprint of a target
    :return: a fingerprint representing this target (no dependencies)
    :rtype: string
    """
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    return fingerprint_strategy.fingerprint_target(self)

  def invalidation_hash(self, fingerprint_strategy=None):
    """
    :API: public
    """
    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()
    if fingerprint_strategy not in self._cached_fingerprint_map:
      self._cached_fingerprint_map[fingerprint_strategy] = self.compute_invalidation_hash(fingerprint_strategy)
    return self._cached_fingerprint_map[fingerprint_strategy]

  def mark_extra_invalidation_hash_dirty(self):
    """
    :API: public
    """

  def mark_invalidation_hash_dirty(self):
    """Invalidates memoized fingerprints for this target, including those in payloads.

    Exposed for testing.

    :API: public
    """
    self._cached_fingerprint_map = {}
    self._cached_all_transitive_fingerprint_map = {}
    self._cached_direct_transitive_fingerprint_map = {}
    self.mark_extra_invalidation_hash_dirty()
    self.payload.mark_dirty()

  def transitive_invalidation_hash(self, fingerprint_strategy=None, depth=0):
    """
    :API: public

    :param FingerprintStrategy fingerprint_strategy: optional fingerprint strategy to use to compute
    the fingerprint of a target
    :return: A fingerprint representing this target and all of its dependencies.
      The return value can be `None`, indicating that this target and all of its transitive dependencies
      did not contribute to the fingerprint, according to the provided FingerprintStrategy.
    :rtype: string
    """
    if depth > self._MAX_RECURSION_DEPTH:
      # NB(zundel) without this catch, we'll eventually hit the python stack limit
      # RuntimeError: maximum recursion depth exceeded while calling a Python object
      raise self.RecursiveDepthError("Max depth of {} exceeded.".format(self._MAX_RECURSION_DEPTH))

    fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()

    direct = (depth == 0 and fingerprint_strategy.direct(self))
    if direct:
      fingerprint_map = self._cached_direct_transitive_fingerprint_map
    else:
      fingerprint_map = self._cached_all_transitive_fingerprint_map

    if fingerprint_strategy not in fingerprint_map:
      hasher = sha1()

      def dep_hash_iter():
        dep_list = fingerprint_strategy.dependencies(self) if direct else self.dependencies
        for dep in dep_list:
          try:
            if direct:
              dep_hash = dep.invalidation_hash(fingerprint_strategy)
            else:
              dep_hash = dep.transitive_invalidation_hash(fingerprint_strategy, depth=depth+1)
            if dep_hash is not None:
              yield dep_hash
          except self.RecursiveDepthError as e:
            raise self.RecursiveDepthError("{message}\n  referenced from {spec}"
                                           .format(message=e, spec=dep.address.spec))

      dep_hashes = sorted(list(dep_hash_iter()))
      for dep_hash in dep_hashes:
        hasher.update(dep_hash)
      target_hash = self.invalidation_hash(fingerprint_strategy)
      if target_hash is None and not dep_hashes:
        return None
      dependencies_hash = hasher.hexdigest()[:12]
      combined_hash = '{target_hash}.{deps_hash}'.format(target_hash=target_hash,
                                                         deps_hash=dependencies_hash)
      fingerprint_map[fingerprint_strategy] = combined_hash
    return fingerprint_map[fingerprint_strategy]

  def mark_transitive_invalidation_hash_dirty(self):
    """
    :API: public
    """
    self._cached_all_transitive_fingerprint_map = {}
    self._cached_direct_transitive_fingerprint_map = {}
    self.mark_extra_transitive_invalidation_hash_dirty()

  def mark_extra_transitive_invalidation_hash_dirty(self):
    """
    :API: public
    """

  def inject_dependency(self, dependency_address):
    """
    :API: public
    """
    self._build_graph.inject_dependency(dependent=self.address, dependency=dependency_address)

    def invalidate_dependee(dependee):
      dependee.mark_transitive_invalidation_hash_dirty()
    self._build_graph.walk_transitive_dependee_graph([self.address], work=invalidate_dependee)

  @property
  def _sources_field(self):
    sources_field = self.payload.get_field('sources')
    if sources_field is not None:
      return sources_field
    return SourcesField(sources=FilesetWithSpec.empty(self.address.spec_path))

  def has_sources(self, extension=''):
    """
    :API: public

    :param string extension: suffix of filenames to test for
    :return: True if the target contains sources that match the optional extension suffix
    :rtype: bool
    """
    return self._sources_field.has_sources(extension)

  def sources_relative_to_buildroot(self):
    """
    :API: public
    """
    if self.has_sources():
      return self.payload.sources.relative_to_buildroot()
    else:
      return []

  def sources_relative_to_source_root(self):
    """
    :API: public
    """
    if self.has_sources():
      abs_source_root = os.path.join(get_buildroot(), self.target_base)
      for source in self.sources_relative_to_buildroot():
        abs_source = os.path.join(get_buildroot(), source)
        yield os.path.relpath(abs_source, abs_source_root)

  def globs_relative_to_buildroot(self):
    """
    :API: public
    """
    return self._sources_field.filespec

  def sources_relative_to_target_base(self):
    """
    :API: public
    """
    return self.payload.sources.sources

  @property
  def derived_from(self):
    """Returns the target this target was derived from.

    If this target was not derived from another, returns itself.

    :API: public
    """
    return self._build_graph.get_derived_from(self.address)

  @property
  def derived_from_chain(self):
    """Returns all targets that this target was derived from.

    If this target was not derived from another, returns an empty sequence.

    :API: public
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

    :API: public
    """
    return self._build_graph.get_concrete_derived_from(self.address)

  @property
  @deprecated('1.5.0.dev0', 'Use `Target.compute_injectable_specs()` instead.')
  def traversable_specs(self):
    """
    :API: public

    :return: specs referenced by this target to be injected into the build graph
    :rtype: list of strings
    """
    return []

  @property
  @deprecated('1.5.0.dev0', 'Use `Target.compute_dependency_specs()` instead.')
  def traversable_dependency_specs(self):
    """
    :API: public

    :return: specs representing dependencies of this target that will be injected to the build
    graph and linked in the graph as dependencies of this target
    :rtype: list of strings
    """
    return []

  @staticmethod
  def _validate_target_representation_args(kwargs, payload):
    assert kwargs is None or payload is None, 'must provide either kwargs or payload'
    assert not (kwargs is not None and payload is not None), 'may not provide both kwargs and payload'
    assert not (kwargs and not isinstance(kwargs, dict)), (
      'expected a `dict` object for kwargs, instead found a {}'.format(type(kwargs))
    )
    assert not (payload and not isinstance(payload, Payload)), (
      'expected a `Payload` object for payload, instead found a {}'.format(type(payload))
    )

  @classmethod
  def compute_injectable_specs(cls, kwargs=None, payload=None):
    """Given either pre-Target.__init__() kwargs or a post-Target.__init__() payload, compute the specs
    to inject as non-dependencies in the same vein as the prior `traversable_specs`.

    :API: public

    :param dict kwargs: The pre-Target.__init__() kwargs dict.
    :param Payload payload: The post-Target.__init__() Payload object.
    :yields: Spec strings representing dependencies of this target.
    """
    cls._validate_target_representation_args(kwargs, payload)
    # N.B. This pattern turns this method into a non-yielding generator, which is helpful for subclassing.
    return
    yield

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    """Given either pre-Target.__init__() kwargs or a post-Target.__init__() payload, compute the
    full set of dependency specs in the same vein as the prior `traversable_dependency_specs`.

    N.B. This is a temporary bridge to span the gap between v2 "Fields" products vs v1 `BuildGraph`
    `Target` object representations. See:

      https://github.com/pantsbuild/pants/issues/3560
      https://github.com/pantsbuild/pants/issues/3561

    :API: public

    :param dict kwargs: The pre-Target.__init__() kwargs dict.
    :param Payload payload: The post-Target.__init__() Payload object.
    :yields: Spec strings representing dependencies of this target.
    """
    cls._validate_target_representation_args(kwargs, payload)
    # N.B. This pattern turns this method into a non-yielding generator, which is helpful for subclassing.
    return
    yield

  @property
  def dependencies(self):
    """
    :API: public

    :return: targets that this target depends on
    :rtype: list of Target
    """
    return [self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependencies_of(self.address)]

  @property
  def dependents(self):
    """
    :API: public

    :return: targets that depend on this target
    :rtype: list of Target
    """
    return [self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependents_of(self.address)]

  @property
  def is_synthetic(self):
    """
    :API: public

    :return: True if this target did not originate from a BUILD file.
    """
    return self.address in self._build_graph.synthetic_addresses

  @property
  def is_original(self):
    """
    :API: public

    Returns ``True`` if this target is derived from no other.
    """
    return self.derived_from == self

  @memoized_property
  def id(self):
    """A unique and unix safe identifier for the Target.
    Since other classes use this id to generate new file names and unix system has 255 character
    limitation on a file name, 200-character limit is chosen as a safe measure.

    :API: public
    """
    return self.compute_target_id(self.address)

  @property
  def identifier(self):
    """
    :API: public
    """
    return self.id

  def walk(self, work, predicate=None):
    """Walk of this target's dependency graph, DFS preorder traversal, visiting each node exactly
    once.

    If a predicate is supplied it will be used to test each target before handing the target to
    work and descending. Work can return targets in which case these will be added to the walk
    candidate set if not already walked.

    :API: public

    :param work: Callable that takes a :py:class:`pants.build_graph.target.Target`
      as its single argument.
    :param predicate: Callable that takes a :py:class:`pants.build_graph.target.Target`
      as its single argument and returns True if the target should passed to ``work``.
    """
    if not callable(work):
      raise ValueError('work must be callable but was {}'.format(work))
    if predicate and not callable(predicate):
      raise ValueError('predicate must be callable but was {}'.format(predicate))
    self._build_graph.walk_transitive_dependency_graph([self.address], work, predicate)

  def closure(self, *vargs, **kwargs):
    """Returns this target's transitive dependencies.

    The walk will be depth-first in preorder, or breadth first if bfs=True is specified.

    See Target.closure_for_targets().

    :API: public
    """
    return self.closure_for_targets([self], *vargs, **kwargs)

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

  # List of glob patterns, or a single glob pattern.
  # Subclasses can override, typically to specify a file extension (e.g., '*.java').
  default_sources_globs = None

  # List of glob patterns, or a single glob pattern.
  # Subclasses can override, to specify files that should be excluded from the
  # default_sources_globs (e.g., '*Test.java').
  default_sources_exclude_globs = None

  @classmethod
  def supports_default_sources(cls):
    """Whether this target type can provide default sources if none were specified explicitly."""
    return cls.default_sources_globs is not None

  @classmethod
  def default_sources(cls, sources_rel_path):
    """Provide sources, if they weren't specified explicitly in the BUILD file.

    By default this globs over self.default_sources_globs (e.g., '*.java')
    but subclasses can override to provide more nuanced default behavior.
    In this case, the subclasses must also override supports_default_sources().
    """
    if cls.default_sources_globs is not None:
      if cls.default_sources_exclude_globs is not None:
        exclude = [Globs.create_fileset_with_spec(sources_rel_path,
                                                  *maybe_list(cls.default_sources_exclude_globs))]
      else:
        exclude = []
      return Globs.create_fileset_with_spec(sources_rel_path,
                                            *maybe_list(cls.default_sources_globs),
                                            exclude=exclude)
    return None

  def create_sources_field(self, sources, sources_rel_path, key_arg=None):
    """Factory method to create a SourcesField appropriate for the type of the sources object.

    Note that this method is called before the call to Target.__init__ so don't expect fields to
    be populated!

    :API: public

    :return: a payload field object representing the sources parameter
    :rtype: SourcesField
    """
    if sources is None:
      # Make sure we don't apply the defaulting to uses of this method other than for
      # creating a sources= field (e.g., we also use this for creating resources= fields).
      # Note that the check for supports_default_sources() precedes the subsystem check.
      # This is so that tests don't need to set up the subsystem when creating targets that
      # legitimately do not require sources.
      if ((key_arg is None or key_arg == 'sources') and
          self.supports_default_sources() and
          self.Arguments.global_instance().get_options().implicit_sources):
        sources = self.default_sources(sources_rel_path)
      else:
        sources = FilesetWithSpec.empty(sources_rel_path)
    elif isinstance(sources, (set, list, tuple)):
      # Received a literal sources list: convert to a FilesetWithSpec via Files.
      sources = Files.create_fileset_with_spec(sources_rel_path, *sources)
    elif not isinstance(sources, FilesetWithSpec):
      key_arg_section = "'{}' to be ".format(key_arg) if key_arg else ""
      raise TargetDefinitionException(self, "Expected {}a glob, an address or a list, but was {}"
                                            .format(key_arg_section, type(sources)))

    return SourcesField(sources=sources)
