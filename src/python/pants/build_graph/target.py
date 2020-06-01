# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import weakref
from hashlib import sha1
from typing import Optional, Sequence, Union

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import hash_all
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.validation import assert_list
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.target_addressable import TargetAddressable
from pants.build_graph.target_scopes import Scope
from pants.fs.fs import safe_filename
from pants.source.payload_fields import SourcesField
from pants.source.wrapped_globs import FilesetWithSpec
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class AbstractTarget:
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
        """Internal error, too many elements in Addresses.

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

        options_scope = "target-arguments"

        @classmethod
        def register_options(cls, register):
            register(
                "--ignored",
                advanced=True,
                type=dict,
                help="Map of target name to a list of keyword arguments that should be ignored if a "
                "target receives them unexpectedly. Typically used to allow usage of arguments "
                "in BUILD files that are not yet available in the current version of pants.",
            )

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
            # The source argument is automatically promoted to the sources argument, and rules should
            # always use the sources argument; don't error if people used source in their BUILD file.
            # There doesn't appear to be an easy way to error if a Target subclass explicitly takes
            # `source` as a named kwarg; it would be nice to error rather than silently swallow the value,
            # if there were such a way.
            ignore_params.add("source")
            unknown_args = {arg: value for arg, value in kwargs.items() if arg not in ignore_params}
            ignored_args = {arg: value for arg, value in kwargs.items() if arg in ignore_params}
            if ignored_args:
                logger.debug(
                    "{target} ignoring the unimplemented arguments: {args}".format(
                        target=target.address.spec,
                        args=", ".join(
                            "{} = {}".format(key, val) for key, val in ignored_args.items()
                        ),
                    )
                )
            if unknown_args:
                error_message = "{target_type} received unknown arguments: {args}"
                raise self.UnknownArgumentError(
                    target.address.spec,
                    error_message.format(
                        target_type=type(target).__name__,
                        args="".join(
                            "\n  {} = {}".format(key, value) for key, value in unknown_args.items()
                        ),
                    ),
                )

    class TagAssignments(Subsystem):
        """Tags to add to targets in addition to any defined in their BUILD files."""

        options_scope = "target-tag-assignments"

        @classmethod
        def register_options(cls, register):
            register(
                "--tag-targets-mappings",
                type=dict,
                default=None,
                fingerprint=True,
                help='Dict with tag assignments for targets. Ex: { "tag1": ["path/to/target:foo"] }',
            )

        @classmethod
        def tags_for(cls, target_address):
            return cls.global_instance()._invert_tag_targets_mappings().get(target_address, [])

        @memoized_method
        def _invert_tag_targets_mappings(self):
            result = {}
            for tag, targets in (self.get_options().tag_targets_mappings or {}).items():
                for target in targets:
                    target_tags = result.setdefault(Address.parse(target).spec, [])
                    target_tags.append(tag)
            return result

    @classmethod
    def subsystems(cls):
        return super().subsystems() + (cls.Arguments, cls.TagAssignments)

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
            raise TargetDefinitionException(self, "Not under any configured source root.")
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
        return safe_filename(address.path_safe_spec)

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
    def _closure_dep_predicate(
        cls, roots, include_scopes=None, exclude_scopes=None, respect_intransitive=False
    ):
        if not respect_intransitive and include_scopes is None and exclude_scopes is None:
            return None

        root_lookup = set(roots)

        def predicate(target, dep_target):
            if not dep_target.scope.in_scope(
                include_scopes=include_scopes, exclude_scopes=exclude_scopes
            ):
                return False
            # dep_target.transitive == False means that dep_target is only included if target is a root target.
            if respect_intransitive and not dep_target.transitive and target not in root_lookup:
                return False
            return True

        return predicate

    @classmethod
    def closure_for_targets(
        cls,
        target_roots,
        exclude_scopes=None,
        include_scopes=None,
        bfs=None,
        postorder=None,
        respect_intransitive=False,
    ):
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
        target_roots = list(target_roots)  # Sometimes generators are passed into this function.
        if not target_roots:
            return OrderedSet()

        build_graph = target_roots[0]._build_graph
        addresses = [target.address for target in target_roots]
        dep_predicate = cls._closure_dep_predicate(
            target_roots,
            include_scopes=include_scopes,
            exclude_scopes=exclude_scopes,
            respect_intransitive=respect_intransitive,
        )
        closure = OrderedSet()

        if not bfs:
            build_graph.walk_transitive_dependency_graph(
                addresses=addresses,
                work=closure.add,
                postorder=postorder,
                dep_predicate=dep_predicate,
            )
        else:
            closure.update(
                build_graph.transitive_subgraph_of_addresses_bfs(
                    addresses=addresses, dep_predicate=dep_predicate,
                )
            )

        # Make sure all the roots made it into the closure.
        closure.update(target_roots)
        return closure

    def __init__(
        self,
        name,
        address,
        build_graph,
        type_alias=None,
        payload=None,
        tags=None,
        description=None,
        no_cache=False,
        scope=None,
        _transitive=None,
        **kwargs
    ):
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
        self.payload.add_field("scope_string", PrimitiveField(str(scope)))
        self.payload.add_field(
            "transitive", PrimitiveField(True if _transitive is None else _transitive)
        )
        self.payload.freeze()
        self.name = name
        self.address = address
        self._build_graph = weakref.proxy(build_graph)
        self._type_alias = type_alias
        self._tags = set(tags or []).union(self.TagAssignments.tags_for(address.spec))
        self.description = description

        self._cached_fingerprint_map = {}
        self._cached_all_transitive_fingerprint_map = {}
        self._cached_direct_transitive_fingerprint_map = {}
        self._cached_strict_dependencies_map = {}
        self._cached_exports_addresses = None
        self._no_cache = no_cache
        if kwargs:
            self.Arguments.check(self, kwargs)

    @property
    def scope(self):
        return self._scope

    @property
    def transitive(self):
        return self.payload.transitive

    @property
    def no_cache(self):
        return self._no_cache

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

    def assert_list(self, putative_list, expected_type=str, key_arg=None):
        """
        :API: public
        """
        return assert_list(
            putative_list,
            expected_type,
            key_arg=key_arg,
            raise_type=lambda msg: TargetDefinitionException(self, msg),
        )

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
            self._cached_fingerprint_map[fingerprint_strategy] = self.compute_invalidation_hash(
                fingerprint_strategy
            )
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
        self._cached_strict_dependencies_map = {}
        self._cached_exports_addresses = None
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
            raise self.RecursiveDepthError(
                "Max depth of {} exceeded.".format(self._MAX_RECURSION_DEPTH)
            )

        fingerprint_strategy = fingerprint_strategy or DefaultFingerprintStrategy()

        direct = depth == 0 and fingerprint_strategy.direct(self)
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
                            dep_hash = dep.transitive_invalidation_hash(
                                fingerprint_strategy, depth=depth + 1
                            )
                        if dep_hash is not None:
                            yield dep_hash
                    except self.RecursiveDepthError as e:
                        raise self.RecursiveDepthError(
                            "{message}\n  referenced from {spec}".format(
                                message=e, spec=dep.address.spec
                            )
                        )

            dep_hashes = sorted(list(dep_hash_iter()))
            for dep_hash in dep_hashes:
                hasher.update(dep_hash.encode())
            target_hash = self.invalidation_hash(fingerprint_strategy)
            if target_hash is None and not dep_hashes:
                return None
            dependencies_hash = hasher.hexdigest()[:12]
            combined_hash = "{target_hash}.{deps_hash}".format(
                target_hash=target_hash, deps_hash=dependencies_hash
            )
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

    @memoized_property
    def _sources_field(self):
        sources_field = self.payload.get_field("sources")
        if sources_field is not None:
            return sources_field
        return SourcesField(sources=FilesetWithSpec.empty(self.address.spec_path))

    def has_sources(self, extension=None):
        """Return `True` if this target owns sources; optionally of the given `extension`.

        :API: public

        :param string extension: Optional suffix of filenames to test for.
        :return: `True` if the target contains sources that match the optional extension suffix.
        :rtype: bool
        """
        source_paths = self._sources_field.source_paths
        if not source_paths:
            return False
        if not extension:
            return True
        return any(source.endswith(extension) for source in source_paths)

    def sources_relative_to_buildroot(self):
        """
        :API: public
        """
        if self.has_sources():
            return self._sources_field.relative_to_buildroot()
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
        return self._sources_field.sources

    def sources_count(self):
        """Returns the count of source files owned by the target."""
        return len(self._sources_field.sources.files)

    def sources_snapshot(self, scheduler=None):
        """Get a Snapshot of the sources attribute of this target.

        This API is experimental, and is subject to change.
        """
        return self._sources_field.snapshot(scheduler=scheduler)

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

    @staticmethod
    def _validate_target_representation_args(kwargs, payload):
        assert (kwargs is None) ^ (payload is None), "must provide either kwargs or payload"
        assert (kwargs is None) or isinstance(
            kwargs, dict
        ), "expected a `dict` object for kwargs, instead found a {}".format(type(kwargs))
        assert (payload is None) or isinstance(
            payload, Payload
        ), "expected a `Payload` object for payload, instead found a {}".format(type(payload))

    @classmethod
    def compute_injectable_address_specs(cls, kwargs=None, payload=None):
        """Given either pre-Target.__init__() kwargs or a post-Target.__init__() payload, compute
        the address specs to inject as non-dependencies (in the same vein as the prior
        `traversable_specs`).

        :API: public

        :param dict kwargs: The pre-Target.__init__() kwargs dict.
        :param Payload payload: The post-Target.__init__() Payload object.
        :yields: AddressSpec strings representing dependencies of this target.
        """
        cls._validate_target_representation_args(kwargs, payload)
        # N.B. This pattern turns this method into a non-yielding generator, which is helpful for
        # subclassing.
        return
        yield  # type: ignore[unreachable] # MyPy doesn't understand this pattern

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        """Given either pre-Target.__init__() kwargs or a post-Target.__init__() payload, compute
        the full set of dependency address specs (in the same vein as the prior
        `traversable_dependency_specs`).

        N.B. This is a temporary bridge to span the gap between v2 "Fields" products vs v1 `BuildGraph`
        `Target` object representations. See:

          https://github.com/pantsbuild/pants/issues/3560
          https://github.com/pantsbuild/pants/issues/3561

        :API: public

        :param dict kwargs: The pre-Target.__init__() kwargs dict.
        :param Payload payload: The post-Target.__init__() Payload object.
        :yields: AddressSpec strings representing dependencies of this target.
        """
        cls._validate_target_representation_args(kwargs, payload)
        # N.B. This pattern turns this method into a non-yielding generator, which is helpful for
        # subclassing.
        return
        yield  # type: ignore[unreachable] # MyPy doesn't understand this pattern

    @property
    def dependencies(self):
        """
        :API: public

        :return: targets that this target depends on
        :rtype: list of Target
        """
        return [
            self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependencies_of(self.address)
        ]

    @property
    def export_addresses(self):
        exports = self._cached_exports_addresses
        if exports is None:

            exports = []
            for export_spec in getattr(self, "export_specs", tuple()):
                if isinstance(export_spec, Target):
                    exports.append(export_spec.address)
                else:
                    exports.append(Address.parse(export_spec, relative_to=self.address.spec_path))
            exports = tuple(exports)

            dep_addresses = {d.address for d in self.dependencies}
            invalid_export_specs = [a.spec for a in exports if a not in dep_addresses]
            if len(invalid_export_specs) > 0:
                raise TargetDefinitionException(
                    self,
                    "Invalid exports: these exports must also be dependencies\n  {}".format(
                        "\n  ".join(invalid_export_specs)
                    ),
                )

            self._cached_exports_addresses = exports
        return exports

    def strict_dependencies(self, dep_context):
        """
        :param dep_context: A DependencyContext with configuration for the request.
        :return: targets that this target "strictly" depends on. This set of dependencies contains
          only directly declared dependencies, with two exceptions:
            1) aliases are expanded transitively
            2) the strict_dependencies of targets exported targets exported by
          strict_dependencies (transitively).
        :rtype: list of Target
        """
        strict_deps = self._cached_strict_dependencies_map.get(dep_context, None)
        if strict_deps is None:
            default_predicate = self._closure_dep_predicate(
                {self}, **dep_context.target_closure_kwargs
            )
            # TODO(#5977): this branch needs testing!
            if not default_predicate:

                def default_predicate(*args, **kwargs):
                    return True

            def dep_predicate(source, dependency):
                if not default_predicate(source, dependency):
                    return False

                # Always expand aliases.
                if type(source) in dep_context.alias_types:
                    return True

                # Traverse other dependencies if they are exported.
                if source._dep_is_exported(dependency):
                    return True
                return False

            dep_addresses = [d.address for d in self.dependencies if default_predicate(self, d)]
            result = self._build_graph.transitive_subgraph_of_addresses_bfs(
                addresses=dep_addresses, dep_predicate=dep_predicate
            )

            strict_deps = OrderedSet()
            for declared in result:
                if type(declared) in dep_context.alias_types:
                    continue
                if isinstance(declared, dep_context.types_with_closure):
                    strict_deps.update(
                        declared.closure(bfs=True, **dep_context.target_closure_kwargs)
                    )
                strict_deps.add(declared)

            strict_deps = list(strict_deps)
            self._cached_strict_dependencies_map[dep_context] = strict_deps
        return strict_deps

    def _dep_is_exported(self, dependency):
        return (
            dependency.address in self.export_addresses
            or dependency.is_synthetic
            and (dependency.concrete_derived_from.address in self.export_addresses)
        )

    @property
    def dependents(self):
        """
        :API: public

        :return: targets that depend on this target
        :rtype: list of Target
        """
        return [
            self._build_graph.get_target(dep_address)
            for dep_address in self._build_graph.dependents_of(self.address)
        ]

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
        """A unique and unix safe identifier for the Target. Since other classes use this id to
        generate new file names and unix system has 255 character limitation on a file name,
        200-character limit is chosen as a safe measure.

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
        """Walk of this target's dependency graph, DFS preorder traversal, visiting each node
        exactly once.

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
            raise ValueError("work must be callable but was {}".format(work))
        if predicate and not callable(predicate):
            raise ValueError("predicate must be callable but was {}".format(predicate))
        self._build_graph.walk_transitive_dependency_graph([self.address], work, predicate)

    def closure(self, *vargs, **kwargs):
        """Returns this target's transitive dependencies.

        The walk will be depth-first in preorder, or breadth first if bfs=True is specified.

        See Target.closure_for_targets().

        :API: public
        """
        return self.closure_for_targets([self], *vargs, **kwargs)

    def __lt__(self, other):
        return self.address < other.address

    def __eq__(self, other):
        return isinstance(other, Target) and self.address == other.address

    def __hash__(self):
        return hash(self.address)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        addr = self.address if hasattr(self, "address") else "address not yet set"
        return "{}({})".format(type(self).__name__, addr)

    # List of glob patterns, or a single glob pattern.
    # Subclasses can override, typically to specify a file extension (e.g., '*.java').
    default_sources_globs: Optional[Union[str, Sequence[str]]] = None

    # List of glob patterns, or a single glob pattern.
    # Subclasses can override, to specify files that should be excluded from the
    # default_sources_globs (e.g., '*Test.java').
    default_sources_exclude_globs: Optional[Union[str, Sequence[str]]] = None

    @classmethod
    def supports_default_sources(cls):
        """Whether this target type can provide default sources if none were specified
        explicitly."""
        return cls.default_sources_globs is not None

    # TODO: Inline this as SourcesField(sources=sources) when all callers are guaranteed to pass an
    # EagerFilesetWithSpec.
    def create_sources_field(self, sources, sources_rel_path, key_arg=None):
        """Factory method to create a SourcesField appropriate for the type of the sources object.

        Note that this method is called before the call to Target.__init__ so don't expect fields to
        be populated!

        :API: public

        :return: a payload field object representing the sources parameter
        :rtype: SourcesField
        """
        if not sources:
            sources = FilesetWithSpec.empty(sources_rel_path)
        elif not isinstance(sources, FilesetWithSpec):
            key_arg_section = "'{}' to be ".format(key_arg) if key_arg else ""
            raise TargetDefinitionException(
                self,
                "Expected {}a glob, an address or a list, but was {}".format(
                    key_arg_section, type(sources)
                ),
            )

        return SourcesField(sources=sources)
