# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Set, Tuple, Type, cast

from pants.base.exceptions import TargetDefinitionException
from pants.base.specs import AddressSpec, AddressSpecs, SingleAddress
from pants.build_graph.address import Address, BuildFileAddress
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target import Target as TargetV1
from pants.engine.addresses import Addresses
from pants.engine.internals.parser import HydratedStruct
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import RegisteredTargetTypes
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
            return target_cls(build_graph=self, **kwargs)
        except TargetDefinitionException:
            raise
        except Exception as e:
            raise TargetDefinitionException(
                legacy_hydrated_target.build_file_address,
                "Failed to instantiate Target with type {}: {}".format(target_cls, e),
            )

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


@rule
async def transitive_hydrated_targets(
    addresses: Addresses, registered_target_types: RegisteredTargetTypes
) -> TransitiveHydratedTargets:
    """Given Addresses, kicks off recursion on expansion of TransitiveHydratedTargets.

    The TransitiveHydratedTarget struct represents a structure-shared graph, which we walk and
    flatten here. The engine memoizes the computation of TransitiveHydratedTarget, so when multiple
    TransitiveHydratedTarget objects are being constructed for multiple roots, their structure will
    be shared.
    """

    transitive_hydrated_targets = await MultiGet(
        Get(TransitiveHydratedTarget, Address, a) for a in addresses
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
    thts = await Get(TransitiveHydratedTargets, Addresses, addresses)
    roots_bfas = await MultiGet(Get(BuildFileAddress, Address, ht._address) for ht in thts.roots)
    closure_bfas = await MultiGet(
        Get(BuildFileAddress, Address, ht._address) for ht in thts.closure
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
        Get(TransitiveHydratedTarget, Address, d) for d in root.adaptor.dependencies
    )
    return TransitiveHydratedTarget(root, dependencies)


@rule
async def hydrate_target(hydrated_struct: HydratedStruct) -> HydratedTarget:
    """Construct a HydratedTarget from a TargetAdaptor and hydrated versions of its adapted
    fields."""
    target_adaptor = cast(TargetAdaptor, hydrated_struct.value)
    kwargs = target_adaptor.kwargs()
    return HydratedTarget(adaptor=type(target_adaptor)(**kwargs))


def create_legacy_graph_tasks():
    """Create tasks to recursively parse the legacy graph."""
    return [
        transitive_hydrated_target,
        transitive_hydrated_targets,
        legacy_transitive_hydrated_targets,
        hydrate_target,
    ]
