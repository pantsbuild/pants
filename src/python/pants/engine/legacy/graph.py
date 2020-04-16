# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import logging
import os.path
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, DefaultDict, Dict, Iterable, Iterator, List, Set, Tuple, Type, Union, cast

from pants.base.exceptions import ResolveError, TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.base.specs import (
    AddressSpec,
    AddressSpecs,
    AscendantAddresses,
    FilesystemLiteralSpec,
    FilesystemMergedSpec,
    FilesystemResolvedGlobSpec,
    FilesystemSpecs,
    SingleAddress,
)
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.app_base import AppBase, Bundle
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.remote_sources import RemoteSources
from pants.build_graph.target import Target as TargetV1
from pants.engine.addressable import Addresses, AddressesWithOrigins, AddressWithOrigin
from pants.engine.fs import EMPTY_SNAPSHOT, PathGlobs, Snapshot
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.structs import (
    BundleAdaptor,
    BundlesField,
    HydrateableField,
    SourcesField,
    TargetAdaptor,
)
from pants.engine.objects import Collection
from pants.engine.parser import HydratedStruct
from pants.engine.rules import RootRule, UnionMembership, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    Dependencies,
    RegisteredTargetTypes,
    Target,
    Targets,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTarget,
    TransitiveTargets,
    WrappedTarget,
)
from pants.option.global_options import (
    GlobalOptions,
    GlobMatchErrorBehavior,
    OwnersNotFoundBehavior,
)
from pants.source.filespec import any_matches_filespec
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper, Filespec
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


def target_types_from_build_file_aliases(aliases: BuildFileAliases) -> Dict[str, Type[TargetV1]]:
    """Given BuildFileAliases, return the concrete target types constructed for each alias."""
    target_types = dict(aliases.target_types)
    for alias, factory in aliases.target_macro_factories.items():
        (target_type,) = factory.target_types
        target_types[alias] = target_type
    return target_types


@dataclass(frozen=True)
class _DestWrapper:
    """A wrapper for dest field of RemoteSources target.

    This is only used when instantiating RemoteSources target.
    """

    target_types: Any


class LegacyBuildGraph(BuildGraph):
    """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

    This implementation is backed by a Scheduler that is able to resolve
    LegacyTransitiveHydratedTargets.
    """

    @classmethod
    def create(cls, scheduler, build_file_aliases: BuildFileAliases) -> "LegacyBuildGraph":
        """Construct a graph given a Scheduler and BuildFileAliases."""
        return cls(scheduler, target_types_from_build_file_aliases(build_file_aliases))

    def __init__(self, scheduler, target_types: Dict[str, Type[TargetV1]]) -> None:
        """Construct a graph given a Scheduler, and set of target type aliases.

        :param scheduler: A Scheduler that is configured to be able to resolve TransitiveHydratedTargets.
        :param target_types: A dict mapping aliases to target types.
        """
        self._scheduler = scheduler
        self._target_types = target_types
        super().__init__()

    def clone_new(self) -> "LegacyBuildGraph":
        """Returns a new BuildGraph instance of the same type and with the same __init__ params."""
        return LegacyBuildGraph(self._scheduler, self._target_types)

    def _index(self, hydrated_targets: Iterable["LegacyHydratedTarget"]) -> Set[BuildFileAddress]:
        """Index from the given roots into the storage provided by the base class.

        This is an additive operation: any existing connections involving these nodes are preserved.
        """
        all_addresses: Set[BuildFileAddress] = set()
        new_targets: List[TargetV1] = list()

        # Index the ProductGraph.
        for legacy_hydrated_target in hydrated_targets:
            address = legacy_hydrated_target.build_file_address
            all_addresses.add(address)
            if address not in self._target_by_address:
                new_targets.append(self._index_target(legacy_hydrated_target))

        # Once the declared dependencies of all targets are indexed, inject their
        # additional "traversable_(dependency_)?specs".
        deps_to_inject: OrderedSet = OrderedSet()
        addresses_to_inject = set()

        def inject(target: TargetV1, dep_spec: str, is_dependency: bool) -> None:
            address = Address.parse(dep_spec, relative_to=target.address.spec_path)
            if not any(address == t.address for t in target.dependencies):
                addresses_to_inject.add(address)
                if is_dependency:
                    deps_to_inject.add((target.address, address))

        self.apply_injectables(new_targets)

        for target in new_targets:
            for address_spec in target.compute_dependency_address_specs(payload=target.payload):
                inject(target, address_spec, is_dependency=True)

            for address_spec in target.compute_injectable_address_specs(payload=target.payload):
                inject(target, address_spec, is_dependency=False)

        # Inject all addresses, then declare injected dependencies.
        self.inject_addresses_closure(addresses_to_inject)
        for target_address, dep_address in deps_to_inject:
            self.inject_dependency(dependent=target_address, dependency=dep_address)

        return all_addresses

    def _index_target(self, legacy_hydrated_target: "LegacyHydratedTarget") -> TargetV1:
        """Instantiate the given LegacyHydratedTarget, index it in the graph, and return a
        Target."""
        # Instantiate the target.
        address = legacy_hydrated_target.build_file_address
        target = self._instantiate_target(legacy_hydrated_target)
        self._target_by_address[address] = target

        for dependency in legacy_hydrated_target.adaptor.dependencies:
            if dependency in self._target_dependencies_by_address[address]:
                raise self.DuplicateAddressError(
                    "Addresses in dependencies must be unique. "
                    "'{spec}' is referenced more than once by target '{target}'.".format(
                        spec=dependency.spec, target=address.spec
                    )
                )
            # Link its declared dependencies, which will be indexed independently.
            self._target_dependencies_by_address[address].add(dependency)
            self._target_dependees_by_address[dependency].add(address)
        return target

    def _instantiate_target(self, legacy_hydrated_target: "LegacyHydratedTarget") -> TargetV1:
        """Given a LegacyHydratedTarget previously parsed from a BUILD file, instantiate a
        Target."""
        target_cls = self._target_types[legacy_hydrated_target.adaptor.type_alias]
        try:
            # Pop dependencies, which were already consumed during construction.
            kwargs = legacy_hydrated_target.adaptor.kwargs()
            kwargs.pop("dependencies")

            # Replace the `address` field of type `Address` with type `BuildFileAddress`.
            kwargs["address"] = legacy_hydrated_target.build_file_address

            # Instantiate.
            if issubclass(target_cls, AppBase):
                return self._instantiate_app(target_cls, kwargs)
            elif target_cls is RemoteSources:
                return self._instantiate_remote_sources(kwargs)
            return target_cls(build_graph=self, **kwargs)
        except TargetDefinitionException:
            raise
        except Exception as e:
            raise TargetDefinitionException(
                legacy_hydrated_target.build_file_address,
                "Failed to instantiate Target with type {}: {}".format(target_cls, e),
            )

    def _instantiate_app(self, target_cls: Type[TargetV1], kwargs) -> TargetV1:
        """For App targets, convert BundleAdaptor to BundleProps."""
        parse_context = ParseContext(kwargs["address"].spec_path, dict())
        bundleprops_factory = Bundle(parse_context)
        kwargs["bundles"] = [
            bundleprops_factory.create_bundle_props(bundle) for bundle in kwargs["bundles"]
        ]

        return target_cls(build_graph=self, **kwargs)

    def _instantiate_remote_sources(self, kwargs) -> RemoteSources:
        """For RemoteSources target, convert "dest" field to its real target type."""
        kwargs["dest"] = _DestWrapper((self._target_types[kwargs["dest"]],))
        return RemoteSources(build_graph=self, **kwargs)

    def inject_address_closure(self, address: Address) -> None:
        self.inject_addresses_closure([address])

    def inject_addresses_closure(self, addresses: Iterable[Address]) -> None:
        addresses = set(addresses) - set(self._target_by_address.keys())
        if not addresses:
            return
        dependencies = (SingleAddress(directory=a.spec_path, name=a.target_name) for a in addresses)
        for _ in self._inject_address_specs(AddressSpecs(dependencies)):
            pass

    def inject_roots_closure(
        self, address_specs: AddressSpecs, fail_fast=None,
    ) -> Iterator[BuildFileAddress]:
        for address in self._inject_address_specs(address_specs):
            yield address

    def inject_address_specs_closure(
        self, address_specs: Iterable[AddressSpec], fail_fast=None,
    ) -> Iterator[BuildFileAddress]:
        # Request loading of these address specs.
        for address in self._inject_address_specs(AddressSpecs(address_specs)):
            yield address

    def resolve_address(self, address):
        if not self.contains_address(address):
            self.inject_address_closure(address)
        return self.get_target(address)

    @contextmanager
    def _resolve_context(self) -> Iterator[None]:
        try:
            yield
        except Exception as e:
            raise AddressLookupError(
                "Build graph construction failed: {} {}".format(type(e).__name__, str(e))
            )

    def _inject_address_specs(self, address_specs: AddressSpecs) -> Iterator[BuildFileAddress]:
        """Injects targets into the graph for the given `AddressSpecs` object.

        Yields the resulting addresses.
        """
        if not address_specs:
            return

        logger.debug("Injecting address specs to %s: %s", self, address_specs)
        with self._resolve_context():
            (thts,) = self._scheduler.product_request(
                LegacyTransitiveHydratedTargets, [address_specs]
            )

        self._index(thts.closure)

        for hydrated_target in thts.roots:
            yield hydrated_target.build_file_address


class _DependentGraph:
    """A graph for walking dependent addresses of TargetAdaptor objects.

    This avoids/imitates constructing a v1 BuildGraph object, because that codepath results
    in many references held in mutable global state (ie, memory leaks).

    The long term goal is to deprecate the `changed` goal in favor of sufficiently good cache
    hit rates, such that rather than running:

      ./pants --changed-parent=master test

    ...you would always be able to run:

      ./pants test ::

    ...and have it complete in a similar amount of time by hitting relevant caches.
    """

    @classmethod
    def from_iterable(cls, target_types, address_mapper, adaptor_iter):
        """Create a new DependentGraph from an iterable of TargetAdaptor subclasses."""
        inst = cls(target_types, address_mapper)
        all_valid_addresses = set()
        for target_adaptor in adaptor_iter:
            inst._inject_target(target_adaptor)
            all_valid_addresses.add(target_adaptor.address)
        inst._validate(all_valid_addresses)
        return inst

    def __init__(self, target_types, address_mapper):
        # TODO: Dependencies and implicit dependencies are mapped independently, because the latter
        # cannot be validated until:
        #  1) Subsystems are computed in engine: #5869. Currently instantiating a subsystem to find
        #     its injectable specs would require options parsing.
        #  2) Targets-class Subsystem deps can be expanded in-engine (similar to Fields): #4535,
        self._dependent_address_map = defaultdict(set)
        self._implicit_dependent_address_map = defaultdict(set)
        self._target_types = target_types
        self._address_mapper = address_mapper

    def _validate(self, all_valid_addresses):
        """Validate that all of the dependencies in the graph exist in the given addresses set."""
        for dependency, dependents in self._dependent_address_map.items():
            if dependency not in all_valid_addresses:
                raise AddressLookupError(
                    "Dependent graph construction failed: {} did not exist. Was depended on by:\n  {}".format(
                        dependency.spec, "\n  ".join(d.spec for d in dependents)
                    )
                )

    def _inject_target(self, target_adaptor):
        """Inject a target, respecting all sources of dependencies."""
        target_cls = self._target_types[target_adaptor.type_alias]

        declared_deps = target_adaptor.dependencies
        implicit_deps = (
            Address.parse(
                s,
                relative_to=target_adaptor.address.spec_path,
                subproject_roots=self._address_mapper.subproject_roots,
            )
            for s in target_cls.compute_dependency_address_specs(kwargs=target_adaptor.kwargs())
        )
        for dep in declared_deps:
            self._dependent_address_map[dep].add(target_adaptor.address)
        for dep in implicit_deps:
            self._implicit_dependent_address_map[dep].add(target_adaptor.address)

    def dependents_of_addresses(self, addresses):
        """Given an iterable of addresses, return all of those addresses dependents."""
        seen = OrderedSet(addresses)
        for address in addresses:
            seen.update(self._dependent_address_map[address])
            seen.update(self._implicit_dependent_address_map[address])
        return seen

    def transitive_dependents_of_addresses(self, addresses):
        """Given an iterable of addresses, return all of those addresses dependents,
        transitively."""
        closure = set()
        result = []
        to_visit = deque(addresses)

        while to_visit:
            address = to_visit.popleft()
            if address in closure:
                continue

            closure.add(address)
            result.append(address)
            to_visit.extend(self._dependent_address_map[address])
            to_visit.extend(self._implicit_dependent_address_map[address])

        return result


@frozen_after_init
@dataclass
class HydratedTarget:
    """A wrapper for a fully hydrated TargetAdaptor object.

    Why have this type if all information is stored in the underlying TargetAdaptor? We need it for
    the type-driven graph to work properly. A HydratedTarget is a generic wrapper around different
    target classes, whereas a TargetAdaptor has different types like PythonTestsAdaptor and
    PythonLibraryAdaptor. We need to be able to work with targets both generically and depending
    on their target type (i.e. unions).

    Transitive graph walks collect ordered sets of TransitiveHydratedTargets which involve a huge
    amount of hashing: we implement a custom eq/hash to speed that up.
    """

    adaptor: TargetAdaptor

    def __init__(self, adaptor: TargetAdaptor) -> None:
        self.adaptor = adaptor
        # This field is set for efficient lookup of the address in `__hash__` and `__eq__` during
        # graph walks. Directly accessing this field, rather than using `adaptor.address` is about
        # 10x faster. However, rules should still use `adaptor.address` for clarity and because
        # they do not need to access the address as frequently, so it would be an over-optimization
        # (we're talking about 10^-7 vs. 10^-6 seconds here).
        self._address = adaptor.address

    def __hash__(self):
        return hash((self._address, self.adaptor))

    def __eq__(self, other):
        if not isinstance(other, HydratedTarget):
            return NotImplemented
        # NB: This short-circuiting is essential. Without it, constructing the build graph for the
        # Pants repository takes 71 seconds compared to 4.3 seconds!
        if self._address != other._address:
            return False
        return self.adaptor == other.adaptor


class HydratedTargets(Collection[HydratedTarget]):
    """An intransitive set of HydratedTarget objects."""


@dataclass(frozen=True)
class TransitiveHydratedTarget:
    """A recursive structure wrapping a HydratedTarget root and TransitiveHydratedTarget deps."""

    root: HydratedTarget
    dependencies: Tuple["TransitiveHydratedTarget", ...]


@dataclass(frozen=True)
class TransitiveHydratedTargets:
    """A set of HydratedTarget roots, and their transitive, flattened, de-duped closure."""

    roots: Tuple[HydratedTarget, ...]
    closure: FrozenOrderedSet[HydratedTarget]


@dataclass(frozen=True)
class LegacyHydratedTarget:
    """A rip on HydratedTarget for the purpose of V1, which must use BuildFileAddress rather than
    Address."""

    build_file_address: BuildFileAddress
    adaptor: TargetAdaptor

    @staticmethod
    def from_hydrated_target(ht: HydratedTarget, bfa: BuildFileAddress) -> "LegacyHydratedTarget":
        return LegacyHydratedTarget(build_file_address=bfa, adaptor=ht.adaptor)


@dataclass(frozen=True)
class LegacyTransitiveHydratedTargets:
    roots: Tuple[LegacyHydratedTarget, ...]
    closure: FrozenOrderedSet[LegacyHydratedTarget]


@dataclass(frozen=True)
class SourcesSnapshot:
    """Sources matched by command line specs, either directly via FilesystemSpecs or indirectly via
    AddressSpecs.

    Note that the resolved sources do not need an owning target. Any source resolvable by
    `PathGlobs` is valid here.
    """

    snapshot: Snapshot


class SourcesSnapshots(Collection[SourcesSnapshot]):
    """A collection of sources matched by command line specs.

    `@goal_rule`s may request this when they only need source files to operate and do not need any
    target information.
    """


class InvalidOwnersOfArgs(Exception):
    pass


@dataclass(frozen=True)
class OwnersRequest:
    """A request for the owners of a set of file paths."""

    sources: Tuple[str, ...]


@dataclass(frozen=True)
class Owners:
    addresses: Addresses


@rule
async def find_owners(owners_request: OwnersRequest) -> Owners:
    sources_set = FrozenOrderedSet(owners_request.sources)
    dirs_set = FrozenOrderedSet(os.path.dirname(source) for source in sources_set)

    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    candidate_specs = tuple(AscendantAddresses(directory=d) for d in dirs_set)
    candidate_targets = await Get[HydratedTargets](AddressSpecs(candidate_specs))

    # Match the source globs against the expanded candidate targets.
    def owns_any_source(legacy_target: HydratedTarget) -> bool:
        """Given a `HydratedTarget` instance, check if it owns the given source file."""
        target_kwargs = legacy_target.adaptor.kwargs()

        # Handle `sources`-declaring targets.
        # NB: Deleted files can only be matched against the 'filespec' (ie, `PathGlobs`) for a target,
        # so we don't actually call `fileset.matches` here.
        # TODO: This matching logic should be implemented using the rust `fs` crate for two reasons:
        #  1) having two implementations isn't great
        #  2) we're expanding sources via HydratedTarget, but it isn't necessary to do that to match
        target_sources = target_kwargs.get("sources", None)
        return target_sources and any_matches_filespec(
            paths=sources_set, spec=target_sources.filespec
        )

    build_file_addresses = await MultiGet(
        Get[BuildFileAddress](Address, ht.adaptor.address) for ht in candidate_targets
    )
    owners = Addresses(
        ht.adaptor.address
        for ht, bfa in zip(candidate_targets, build_file_addresses)
        if LegacyAddressMapper.any_is_declaring_file(bfa, sources_set) or owns_any_source(ht)
    )
    return Owners(owners)


@rule
async def transitive_hydrated_targets(addresses: Addresses) -> TransitiveHydratedTargets:
    """Given Addresses, kicks off recursion on expansion of TransitiveHydratedTargets.

    The TransitiveHydratedTarget struct represents a structure-shared graph, which we walk and
    flatten here. The engine memoizes the computation of TransitiveHydratedTarget, so when multiple
    TransitiveHydratedTarget objects are being constructed for multiple roots, their structure will
    be shared.
    """

    transitive_hydrated_targets = await MultiGet(
        Get[TransitiveHydratedTarget](Address, a) for a in addresses
    )

    closure: OrderedSet[HydratedTarget] = OrderedSet()
    to_visit = deque(transitive_hydrated_targets)

    while to_visit:
        tht = to_visit.popleft()
        if tht.root in closure:
            continue
        closure.add(tht.root)
        to_visit.extend(tht.dependencies)

    return TransitiveHydratedTargets(
        tuple(tht.root for tht in transitive_hydrated_targets), FrozenOrderedSet(closure)
    )


@rule
async def legacy_transitive_hydrated_targets(
    addresses: Addresses,
) -> LegacyTransitiveHydratedTargets:
    thts = await Get[TransitiveHydratedTargets](Addresses, addresses)
    roots_bfas = await MultiGet(Get[BuildFileAddress](Address, ht._address) for ht in thts.roots)
    closure_bfas = await MultiGet(
        Get[BuildFileAddress](Address, ht._address) for ht in thts.closure
    )
    return LegacyTransitiveHydratedTargets(
        roots=tuple(
            LegacyHydratedTarget.from_hydrated_target(ht, bfa)
            for ht, bfa in zip(thts.roots, roots_bfas)
        ),
        closure=FrozenOrderedSet(
            LegacyHydratedTarget.from_hydrated_target(ht, bfa)
            for ht, bfa in zip(thts.closure, closure_bfas)
        ),
    )


@rule
async def transitive_hydrated_target(root: HydratedTarget) -> TransitiveHydratedTarget:
    dependencies = await MultiGet(
        Get[TransitiveHydratedTarget](Address, d) for d in root.adaptor.dependencies
    )
    return TransitiveHydratedTarget(root, dependencies)


@dataclass(frozen=True)
class HydratedField:
    """A wrapper for a fully constructed replacement kwarg for a HydratedTarget."""

    name: str
    value: Any


@rule
async def hydrate_target(hydrated_struct: HydratedStruct) -> HydratedTarget:
    """Construct a HydratedTarget from a TargetAdaptor and hydrated versions of its adapted
    fields."""
    target_adaptor = cast(TargetAdaptor, hydrated_struct.value)
    # Hydrate the fields of the adaptor and re-construct it.
    hydrated_fields = await MultiGet(
        Get[HydratedField](HydrateableField, fa) for fa in target_adaptor.field_adaptors
    )
    kwargs = target_adaptor.kwargs()
    for field in hydrated_fields:
        kwargs[field.name] = field.value
    return HydratedTarget(adaptor=type(target_adaptor)(**kwargs))


@rule
async def resolve_target(
    hydrated_struct: HydratedStruct,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> WrappedTarget:
    kwargs = hydrated_struct.value.kwargs().copy()
    type_alias = kwargs.pop("type_alias")

    # We special case `address` and the field `name`. The `Target` constructor requires an
    # `Address`, so we use the value pre-calculated via `build_files.py`'s `hydrate_struct` rule.
    # We throw away the field `name` because it can be accessed via `tgt.address.target_name`, so
    # there is no (known) reason to preserve the field.
    address = cast(Address, kwargs.pop("address"))
    kwargs.pop("name", None)

    # We convert `source` into `sources` because the Target API has no `Source` field, only
    # `Sources`.
    if "source" in kwargs and "sources" in kwargs:
        raise TargetDefinitionException(
            address, "Cannot specify both `source` and `sources` fields."
        )
    if "source" in kwargs:
        source = kwargs.pop("source")
        if not isinstance(source, str):
            raise TargetDefinitionException(
                address,
                f"The `source` field must be a string containing a path relative to the target, "
                f"but got {source} of type {type(source)}.",
            )
        kwargs["sources"] = [source]

    target_type = registered_target_types.aliases_to_types.get(type_alias, None)
    if target_type is None:
        raise TargetDefinitionException(
            address,
            f"Target type {repr(type_alias)} is not recognized. All valid target types: "
            f"{sorted(registered_target_types.aliases)}.",
        )

    # Not every target type has the Dependencies field registered, but the StructWithDependencies
    # code means that `kwargs` will always have an entry. We must remove `dependencies` from
    # `kwargs` for target types without the value, otherwise we'll get an "unrecognized field"
    # error. But, we also need to be careful to error if the user did explicitly specify
    # `dependencies` in the BUILD file.
    if kwargs["dependencies"] is None and not target_type.class_has_field(
        Dependencies, union_membership=union_membership
    ):
        kwargs.pop("dependencies")

    return WrappedTarget(target_type(kwargs, address=address))


@rule
async def resolve_target_with_origin(address_with_origin: AddressWithOrigin) -> TargetWithOrigin:
    wrapped_target = await Get[WrappedTarget](Address, address_with_origin.address)
    return TargetWithOrigin(wrapped_target.target, address_with_origin.origin)


@rule
async def resolve_targets(addresses: Addresses) -> Targets:
    wrapped_targets = await MultiGet(Get[WrappedTarget](Address, a) for a in addresses)
    return Targets(wrapped_target.target for wrapped_target in wrapped_targets)


@rule
async def transitive_target(wrapped_root: WrappedTarget) -> TransitiveTarget:
    root = wrapped_root.target
    dependencies = (
        await MultiGet(Get[TransitiveTarget](Address, d) for d in root[Dependencies].value or ())
        if root.has_field(Dependencies)
        else tuple()
    )
    return TransitiveTarget(root, dependencies)


@rule
async def transitive_targets(addresses: Addresses) -> TransitiveTargets:
    """Given Addresses, kicks off recursion on expansion of TransitiveTargets.

    The TransitiveTarget dataclass represents a structure-shared graph, which we walk and flatten
    here. The engine memoizes the computation of TransitiveTarget, so when multiple
    TransitiveTargets objects are being constructed for multiple roots, their structure will be
    shared.
    """
    transitive_targets = await MultiGet(Get[TransitiveTarget](Address, a) for a in addresses)

    closure: OrderedSet[Target] = OrderedSet()
    to_visit = deque(transitive_targets)

    while to_visit:
        tt = to_visit.popleft()
        if tt.root in closure:
            continue
        closure.add(tt.root)
        to_visit.extend(tt.dependencies)

    return TransitiveTargets(tuple(tt.root for tt in transitive_targets), FrozenOrderedSet(closure))


@rule
async def resolve_targets_with_origins(
    addresses_with_origins: AddressesWithOrigins,
) -> TargetsWithOrigins:
    targets_with_origins = await MultiGet(
        Get[TargetWithOrigin](AddressWithOrigin, address_with_origin)
        for address_with_origin in addresses_with_origins
    )
    return TargetsWithOrigins(targets_with_origins)


@rule
async def hydrated_targets(addresses: Addresses) -> HydratedTargets:
    targets = await MultiGet(Get[HydratedTarget](Address, a) for a in addresses)
    return HydratedTargets(targets)


def _eager_fileset_with_spec(
    spec_path: str, filespec: Filespec, snapshot: Snapshot, include_dirs: bool = False,
) -> EagerFilesetWithSpec:
    rel_include_globs = filespec["globs"]

    relpath_adjusted_filespec = FilesetRelPathWrapper.to_filespec(rel_include_globs, spec_path)
    if "exclude" in filespec:
        relpath_adjusted_filespec["exclude"] = [
            FilesetRelPathWrapper.to_filespec(e["globs"], spec_path) for e in filespec["exclude"]
        ]

    return EagerFilesetWithSpec(
        spec_path, relpath_adjusted_filespec, snapshot, include_dirs=include_dirs
    )


@rule
async def hydrate_sources(
    sources_field: SourcesField, glob_match_error_behavior: GlobMatchErrorBehavior,
) -> HydratedField:
    """Given a SourcesField, request a Snapshot for its path_globs and create an
    EagerFilesetWithSpec."""
    address = sources_field.address
    path_globs = dataclasses.replace(
        sources_field.path_globs,
        glob_match_error_behavior=glob_match_error_behavior,
        # TODO(#9012): add line number referring to the sources field. When doing this, we'll likely
        # need to `await Get[BuildFileAddress](Address)`.
        description_of_origin=(
            f"{address}'s `{sources_field.arg}` field"
            if glob_match_error_behavior != GlobMatchErrorBehavior.ignore
            else None
        ),
    )
    snapshot = await Get[Snapshot](PathGlobs, path_globs)
    fileset_with_spec = _eager_fileset_with_spec(
        spec_path=address.spec_path,
        filespec=sources_field.source_globs.filespecs,
        snapshot=snapshot,
    )
    sources_field.validate_fn(fileset_with_spec)
    return HydratedField(sources_field.arg, fileset_with_spec)


@rule
async def hydrate_bundles(
    bundles_field: BundlesField, glob_match_error_behavior: GlobMatchErrorBehavior,
) -> HydratedField:
    """Given a BundlesField, request Snapshots for each of its filesets and create
    BundleAdaptors."""
    address = bundles_field.address
    path_globs_with_match_errors = [
        dataclasses.replace(
            pg,
            glob_match_error_behavior=glob_match_error_behavior,
            # TODO(#9012): add line number referring to the bundles field. When doing this, we'll likely
            # need to `await Get[BuildFileAddress](Address)`.
            description_of_origin=(
                f"{address}'s `bundles` field"
                if glob_match_error_behavior != GlobMatchErrorBehavior.ignore
                else None
            ),
        )
        for pg in bundles_field.path_globs_list
    ]
    snapshot_list = await MultiGet(
        Get[Snapshot](PathGlobs, pg) for pg in path_globs_with_match_errors
    )

    bundles = []
    zipped = zip(bundles_field.bundles, bundles_field.filespecs_list, snapshot_list)
    for bundle, filespecs, snapshot in zipped:
        rel_spec_path = getattr(bundle, "rel_path", address.spec_path)
        kwargs = bundle.kwargs()
        # NB: We `include_dirs=True` because bundle filesets frequently specify directories in order
        # to trigger a (deprecated) default inclusion of their recursive contents. See the related
        # deprecation in `pants.backend.jvm.tasks.bundle_create`.
        kwargs["fileset"] = _eager_fileset_with_spec(
            rel_spec_path, filespecs, snapshot, include_dirs=True
        )
        bundles.append(BundleAdaptor(**kwargs))
    return HydratedField("bundles", bundles)


@rule
async def hydrate_sources_snapshot(hydrated_struct: HydratedStruct) -> SourcesSnapshot:
    """Construct a SourcesSnapshot from a TargetAdaptor without hydrating any other fields."""
    target_adaptor = cast(TargetAdaptor, hydrated_struct.value)
    sources_field = next(
        (fa for fa in target_adaptor.field_adaptors if isinstance(fa, SourcesField)), None
    )
    if sources_field is None:
        return SourcesSnapshot(EMPTY_SNAPSHOT)
    hydrated_sources_field = await Get[HydratedField](HydrateableField, sources_field)
    efws = cast(EagerFilesetWithSpec, hydrated_sources_field.value)
    return SourcesSnapshot(efws.snapshot)


@rule
async def sources_snapshots_from_address_specs(address_specs: AddressSpecs) -> SourcesSnapshots:
    """Request SourcesSnapshots for the given address specs.

    Each address will map to a corresponding SourcesSnapshot. This rule avoids hydrating any other
    fields.
    """
    addresses = await Get[Addresses](AddressSpecs, address_specs)
    snapshots = await MultiGet(Get[SourcesSnapshot](Address, a) for a in addresses)
    return SourcesSnapshots(snapshots)


@rule
async def sources_snapshots_from_filesystem_specs(
    filesystem_specs: FilesystemSpecs, global_options: GlobalOptions,
) -> SourcesSnapshots:
    """Resolve the snapshot associated with the provided filesystem specs."""
    snapshot = await Get[Snapshot](
        PathGlobs,
        filesystem_specs.to_path_globs(
            global_options.options.owners_not_found_behavior.to_glob_match_error_behavior()
        ),
    )
    return SourcesSnapshots([SourcesSnapshot(snapshot)])


@rule
async def addresses_with_origins_from_filesystem_specs(
    filesystem_specs: FilesystemSpecs, global_options: GlobalOptions,
) -> AddressesWithOrigins:
    """Find the owner(s) for each FilesystemSpec while preserving the original FilesystemSpec those
    owners come from.

    This will merge FilesystemSpecs that come from the same owning target into a single
    FilesystemMergedSpec.
    """
    pathglobs_per_include = (
        filesystem_specs.path_globs_for_spec(
            spec, global_options.options.owners_not_found_behavior.to_glob_match_error_behavior(),
        )
        for spec in filesystem_specs.includes
    )
    snapshot_per_include = await MultiGet(
        Get[Snapshot](PathGlobs, pg) for pg in pathglobs_per_include
    )
    owners_per_include = await MultiGet(
        Get[Owners](OwnersRequest(sources=snapshot.files)) for snapshot in snapshot_per_include
    )
    addresses_to_specs: DefaultDict[
        Address, List[Union[FilesystemLiteralSpec, FilesystemResolvedGlobSpec]]
    ] = defaultdict(list)
    for spec, snapshot, owners in zip(
        filesystem_specs.includes, snapshot_per_include, owners_per_include
    ):
        if (
            global_options.options.owners_not_found_behavior != OwnersNotFoundBehavior.ignore
            and isinstance(spec, FilesystemLiteralSpec)
            and not owners.addresses
        ):
            file_path = PurePath(spec.to_spec_string())
            msg = (
                f"No owning targets could be found for the file `{file_path}`.\n\nPlease check "
                f"that there is a BUILD file in `{file_path.parent}` with a target whose `sources` field "
                f"includes `{file_path}`. See https://www.pantsbuild.org/build_files.html."
            )
            if global_options.options.owners_not_found_behavior == OwnersNotFoundBehavior.warn:
                logger.warning(msg)
            else:
                raise ResolveError(msg)
        # We preserve what literal files any globs resolved to. This allows downstream goals to be
        # more precise in which files they operate on.
        origin: Union[FilesystemLiteralSpec, FilesystemResolvedGlobSpec] = (
            spec
            if isinstance(spec, FilesystemLiteralSpec)
            else FilesystemResolvedGlobSpec(glob=spec.glob, files=snapshot.files)
        )
        for address in owners.addresses:
            addresses_to_specs[address].append(origin)
    return AddressesWithOrigins(
        AddressWithOrigin(
            address, specs[0] if len(specs) == 1 else FilesystemMergedSpec.create(specs)
        )
        for address, specs in addresses_to_specs.items()
    )


def create_legacy_graph_tasks():
    """Create tasks to recursively parse the legacy graph."""
    return [
        transitive_hydrated_target,
        transitive_hydrated_targets,
        legacy_transitive_hydrated_targets,
        resolve_target,
        resolve_target_with_origin,
        resolve_targets,
        resolve_targets_with_origins,
        transitive_target,
        transitive_targets,
        hydrate_target,
        hydrated_targets,
        find_owners,
        hydrate_sources,
        hydrate_bundles,
        hydrate_sources_snapshot,
        addresses_with_origins_from_filesystem_specs,
        sources_snapshots_from_address_specs,
        sources_snapshots_from_filesystem_specs,
        RootRule(FilesystemSpecs),
        RootRule(OwnersRequest),
    ]
