# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Synthetic targets is a concept of injecting targets into the build graph that doesn't have a home
in any BUILD file.

This is achieved by declaring a union member for the `SyntheticTargetsRequest` union along
with a rule taking that member and returning a collection of `SyntheticAddressMap`s.

Example demonstrating how to register synthetic targets:

    from dataclasses import dataclass
    from pants.engine.internals.synthetic_targets import (
        SyntheticAddressMaps,
        SyntheticTargetsRequest,
        SyntheticTargetsSpecPaths,
    )
    from pants.engine.internals.target_adaptor import TargetAdaptor
    from pants.engine.rules import collect_rules, rule


    @dataclass(frozen=True)
    class SyntheticExampleTargetsRequest(SyntheticTargetsRequest):
        path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


    class SyntheticExampleTargetsPerDirectorySpecPathsRequest:
        pass


    @dataclass(frozen=True)
    class SyntheticExampleTargetsPerDirectoryRequest(SyntheticTargetsRequest):
        path: str = SyntheticTargetsRequest.REQUEST_TARGETS_PER_DIRECTORY

        # Optional: (without it, only paths with BUILD files will be consistently considered)
        spec_paths_request = SyntheticExampleTargetsPerDirectorySpecPathsRequest


    @rule
    def example_synthetic_targets_per_directory_spec_paths(
        request: SyntheticExampleTargetsPerDirectorySpecPathsRequest,
    ) -> SyntheticTargetsSpecPaths:
        # Return all paths we have targets for.
        # This may involve using GlobPaths etc to discover files in the project source tree.
        known_paths = ["src/a/dir1", "src/a/dir2", ...]
        return SyntheticTargetsSpecPaths.from_paths(known_paths)


    @rule
    async def example_synthetic_targets(request: SyntheticExampleTargetsRequest) -> SyntheticAddressMaps:
        # Return targets for `request.path`.
        return SyntheticAddressMaps.for_targets_request(
            request,
            [
                (
                  "BUILD.synthetic-example",
                  (
                    TargetAdaptor("<type-alias>", "<name>", description_of_origin="...", **kwargs),
                    ...
                  ),
                ),
                ...
            ]
        )


    def rules():
        return (
            *collect_rules(),
            SyntheticExampleTargetsRequest.rules(),
            SyntheticExampleTargetsPerDirectoryRequest.rules(),
            ...
        )
"""
from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import ClassVar, Iterable, Iterator, Sequence

from pants.base.specs import GlobSpecsProtocol
from pants.engine.collection import Collection
from pants.engine.internals.defaults import BuildFileDefaults
from pants.engine.internals.mapper import AddressMap
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import InvalidTargetException
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class SyntheticTargetsSpecPathsRequest:
    specs: tuple[GlobSpecsProtocol, ...]


class SyntheticTargetsSpecPaths(Collection[str]):
    @staticmethod
    def from_paths(paths: Iterable[str]) -> SyntheticTargetsSpecPaths:
        return SyntheticTargetsSpecPaths(sorted(set(paths)))

    @staticmethod
    def from_request(
        request: SyntheticTargetsSpecPathsRequest, paths: Iterable[str]
    ) -> SyntheticTargetsSpecPaths:
        return SyntheticTargetsSpecPaths.from_paths(
            filter(
                lambda path: any(spec.matches_target_residence_dir(path) for spec in request.specs),
                paths,
            )
        )


@union
@dataclass(frozen=True)
class SyntheticTargetsRequest:
    """Union members of the `SyntheticTargetsRequest` should implement a rule returning an instance
    of a `SyntheticAddressMaps`."""

    REQUEST_TARGETS_PER_DIRECTORY: ClassVar[str] = "*"
    SINGLE_REQUEST_FOR_ALL_TARGETS: ClassVar[str] = ""

    path: str = REQUEST_TARGETS_PER_DIRECTORY
    """
    The default field value is used to filter which paths to request targets for, and should be
    declared as appropriate by union members subclassing `SyntheticTargetsRequest`. The
    SINGLE_REQUEST_FOR_ALL_TARGETS will make a single request for all targets at once, while
    REQUEST_TARGETS_PER_DIRECTORY will request all targets for a particular path at a time. Any
    other value will be used as filter to only request targets for that specific directory.

    The rule processing this request should inspect `request.path` to only include targets for that
    directory, unless `request.path` is `SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS` in
    which case _all_ synthetic targets should be returned.
    """

    spec_paths_request: ClassVar[type | None] = None
    """Request class for providing paths in addition to those where BUILD files are found.

    Implement a rule that takes `spec_paths_request` and returns an `SyntheticTargetsSpecPaths`.
    """

    @union
    class _SpecPathsRequest:
        """Protected union type."""

    @classmethod
    def rules(cls) -> Iterator[UnionRule]:
        yield UnionRule(SyntheticTargetsRequest, cls)
        if cls.spec_paths_request is not None:
            yield UnionRule(SyntheticTargetsRequest._SpecPathsRequest, cls.spec_paths_request)


class SyntheticAddressMap(AddressMap):
    def process_declared_targets(self, address_map: AddressMap) -> None:
        for name, target_adaptor in address_map.name_to_target_adaptor.items():
            extend_synthetic = target_adaptor.kwargs.pop("_extend_synthetic", False)
            if name not in self.name_to_target_adaptor:
                if extend_synthetic:
                    raise InvalidTargetException(
                        softwrap(
                            f"""
                            The `{target_adaptor.type_alias}` target {name!r} in {address_map.path}
                            has `_extend_synthetic=True` but there is no synthetic target to extend.
                            """
                        )
                    )
                continue

            # Pop synthetic target to let the explicit target declared in BUILD file take
            # precedence.
            synthetic_target_adaptor = self.name_to_target_adaptor.pop(name)

            if not extend_synthetic:
                # The explicitly declared target should replace the synthetic one.
                continue

            # Check target type matches, when marked as extending the synthetic target.
            if synthetic_target_adaptor.type_alias != target_adaptor.type_alias:
                raise InvalidTargetException(
                    softwrap(
                        f"""
                        The `{target_adaptor.type_alias}` target {name!r} in {address_map.path} is
                        of a different type than the synthetic target
                        `{synthetic_target_adaptor.type_alias}` from {self.path}.

                        When `_extend_synthetic` is true the target types must match, set this to
                        false if you want to replace the synthetic target with the target from your
                        BUILD file.
                        """
                    )
                )

            # Preserve synthetic field values not overriden by the declared target from the BUILD.
            synthetic_target_adaptor.kwargs.update(target_adaptor.kwargs)
            target_adaptor.kwargs = synthetic_target_adaptor.kwargs

    def apply_defaults(self, defaults: BuildFileDefaults) -> None:
        for target_adaptor in self.name_to_target_adaptor.values():
            default_values = defaults.get(target_adaptor.type_alias)
            if default_values is not None:
                target_adaptor.kwargs = {**default_values, **target_adaptor.kwargs}


@dataclass(frozen=True)
class SyntheticAddressMapsRequest:
    """Request all registered synthetic targets for a given path."""

    path: str


class SyntheticAddressMaps(Collection[SyntheticAddressMap]):
    """A collection of `SyntheticAddressMap` for all synthetic target adaptors."""

    @classmethod
    def for_targets_request(
        cls,
        request: SyntheticTargetsRequest,
        synthetic_target_adaptors: Iterable[tuple[str, Iterable[TargetAdaptor]]],
    ) -> SyntheticAddressMaps:
        return cls(
            [
                SyntheticAddressMap.create(os.path.join(request.path, filename), target_adaptors)
                for filename, target_adaptors in synthetic_target_adaptors
            ]
        )


@dataclass(frozen=True)
class AllSyntheticAddressMaps:
    """All pre-loaded SyntheticAddressMaps per directory."""

    address_maps: FrozenDict[str, SyntheticAddressMaps]
    path_request_types: FrozenDict[str, Sequence[type[SyntheticTargetsRequest]]]
    spec_paths: Sequence[str]

    @classmethod
    def create(
        cls,
        address_maps: Iterable[SyntheticAddressMap],
        requests: Iterable[SyntheticTargetsRequest],
        spec_paths: Iterable[str],
    ) -> AllSyntheticAddressMaps:
        def address_map_key(address_map: SyntheticAddressMap) -> str:
            return os.path.dirname(address_map.path)

        def requests_key(request: SyntheticAddressMapsRequest) -> str:
            return request.path

        return AllSyntheticAddressMaps(
            address_maps=FrozenDict(
                {
                    path: SyntheticAddressMaps(address_maps_group)
                    for path, address_maps_group in itertools.groupby(
                        sorted(address_maps, key=address_map_key), key=address_map_key
                    )
                }
            ),
            path_request_types=FrozenDict(
                {
                    path: tuple(type(request) for request in requests_group)  # type: ignore[misc]
                    for path, requests_group in itertools.groupby(
                        sorted(requests, key=requests_key), key=requests_key  # type: ignore[arg-type]
                    )
                    if path != SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS
                }
            ),
            spec_paths=tuple(sorted(spec_paths)),
        )

    def targets_request_types(self, path: str) -> Iterable[type[SyntheticTargetsRequest]]:
        yield from self.path_request_types.get(
            SyntheticTargetsRequest.REQUEST_TARGETS_PER_DIRECTORY, ()
        )
        yield from self.path_request_types.get(path, ())


@rule
async def get_synthetic_address_maps(
    request: SyntheticAddressMapsRequest,
    all_synthetic: AllSyntheticAddressMaps,
) -> SyntheticAddressMaps:
    per_directory_address_maps = await MultiGet(
        Get(SyntheticAddressMaps, SyntheticTargetsRequest, request_type(request.path))
        for request_type in all_synthetic.targets_request_types(request.path)
    )

    return SyntheticAddressMaps(
        itertools.chain(
            all_synthetic.address_maps.get(request.path, ()), *per_directory_address_maps
        )
    )


@rule
async def all_synthetic_targets(union_membership: UnionMembership) -> AllSyntheticAddressMaps:
    requests = [request_type() for request_type in union_membership.get(SyntheticTargetsRequest)]
    all_synthetic = await MultiGet(
        Get(SyntheticAddressMaps, SyntheticTargetsRequest, request)
        for request in requests
        if request.path == SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS
    )
    all_spec_paths = await MultiGet(
        Get(
            SyntheticTargetsSpecPaths,
            SyntheticTargetsRequest._SpecPathsRequest,
            spec_paths_request(),
        )
        for spec_paths_request in union_membership.get(SyntheticTargetsRequest._SpecPathsRequest)
    )
    return AllSyntheticAddressMaps.create(
        address_maps=itertools.chain.from_iterable(all_synthetic),
        requests=requests,
        spec_paths=set(itertools.chain.from_iterable(all_spec_paths)),
    )


@rule
def get_synthetic_targets_spec_paths(
    request: SyntheticTargetsSpecPathsRequest, all_synthetic: AllSyntheticAddressMaps
) -> SyntheticTargetsSpecPaths:
    """Return all known paths for synthetic targets."""
    return SyntheticTargetsSpecPaths.from_request(
        request, itertools.chain(all_synthetic.address_maps, all_synthetic.spec_paths)
    )


def rules():
    return collect_rules()
