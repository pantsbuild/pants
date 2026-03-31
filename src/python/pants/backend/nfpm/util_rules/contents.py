# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.nfpm.field_sets import NfpmContentFileFieldSet
from pants.core.goals.package import PackageFieldSet, TraverseIfNotPackageTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.graph import find_valid_field_sets
from pants.engine.internals.graph import transitive_targets as get_transitive_targets
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule


@dataclass(frozen=True)
class GetPackageFieldSetsForNfpmContentFileDepsRequest:
    addresses: Addresses
    field_set_types: tuple[type[PackageFieldSet], ...]

    def __init__(
        self, addresses: Iterable[Address], field_set_types: Iterable[type[PackageFieldSet]]
    ):
        object.__setattr__(self, "addresses", Addresses(addresses))
        object.__setattr__(self, "field_set_types", tuple(field_set_types))


@dataclass(frozen=True)
class PackageFieldSetsForNfpmContentFileDeps:
    nfpm_content_file_targets: TransitiveTargets
    package_field_sets: FieldSetsPerTarget


@rule
async def get_package_field_sets_for_nfpm_content_file_deps(
    request: GetPackageFieldSetsForNfpmContentFileDepsRequest,
    union_membership: UnionMembership,
) -> PackageFieldSetsForNfpmContentFileDeps:
    def transitive_targets_request(roots: Iterable[Address]):
        return TransitiveTargetsRequest(
            tuple(roots),
            should_traverse_deps_predicate=TraverseIfNotPackageTarget(
                roots=tuple(roots),
                union_membership=union_membership,
            ),
        )

    transitive_targets: TransitiveTargets = await get_transitive_targets(
        transitive_targets_request(request.addresses), **implicitly()
    )
    content_file_transitive_targets: TransitiveTargets = await get_transitive_targets(
        transitive_targets_request(
            [
                tgt.address
                for tgt in transitive_targets.dependencies
                if NfpmContentFileFieldSet.is_applicable(tgt)
            ]
        ),
        **implicitly(),
    )
    package_field_sets: FieldSetsPerTarget = await find_valid_field_sets(
        FieldSetsPerTargetRequest(
            PackageFieldSet,  # has to be a union parent
            [
                tgt
                for tgt in content_file_transitive_targets.dependencies
                if any(
                    field_set_type.is_applicable(tgt) for field_set_type in request.field_set_types
                )
            ],
        ),
        **implicitly(),
    )
    return PackageFieldSetsForNfpmContentFileDeps(
        content_file_transitive_targets, package_field_sets
    )


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
