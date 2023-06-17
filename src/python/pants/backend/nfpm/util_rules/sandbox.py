# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDstField,
    NfpmContentSymlinkDstField,
)
from pants.backend.nfpm.field_sets import NFPM_PACKAGE_FIELD_SET_TYPES, NfpmPackageFieldSet
from pants.backend.nfpm.target_types import NfpmContentFile, NfpmPackageTarget
from pants.core.goals.package import PackageFieldSet, BuiltPackage, EnvironmentAwarePackageRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    Target,
    TransitiveTargets,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
)
from pants.engine.unions import UnionMembership


@dataclass(frozen=True)
class _NfpmSortedDeps:
    nfpm_content_targets: tuple[NfpmContentFile, ...]
    nfpm_package_targets: tuple[NfpmPackageTarget, ...]
    package_targets: tuple[Target, ...]
    remaining_targets: tuple[Target, ...]

    @classmethod
    def sort(
        cls,
        field_set: NfpmPackageFieldSet,
        transitive_targets: TransitiveTargets,
        union_membership: UnionMembership,
    ) -> _NfpmSortedDeps:
        package_field_set_types = (
            union_membership.get(PackageFieldSet) - NFPM_PACKAGE_FIELD_SET_TYPES
        )

        nfpm_content_targets: list[NfpmContentFile] = []
        nfpm_package_targets: list[NfpmPackageTarget] = []
        package_targets: list[Target] = []
        remaining_targets: list[Target] = []

        # NB: TransitiveTargets is AFTER target generation/expansion (so there are no target generators)
        for tgt in transitive_targets.dependencies:
            if tgt.has_field(NfpmContentDirDstField) or tgt.has_field(NfpmContentSymlinkDstField):
                # NfpmContentDir and NfpmContentSymlink targets don't go in the sandbox.
                # They're only registered in the nfpm config.
                continue
            elif tgt.has_field(NfpmContentDstField):
                # an NfpmContentFile DOES need something in the sandbox
                nfpm_content_targets.append(cast(tgt, NfpmContentFile))
                # TODO: sort these into
                #       - relocations (source+src)
                #       - files (source only)
                #         these should be hydrated as Files (along with all the remaining_targets)
                #       - validations (src only => pull from dependencies)
                #         these are used to ensure src exists in the sandbox_digest
                continue

            # This bool serves as a "continue" for the outer "for tgt" loop.
            identified_target = False

            for field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES:
                if field_set_type.is_applicable(tgt):
                    identified_target = True
                    # we only respect nfpm package deps for the same packager
                    # (For example, deb targets will ignore any deps on rpm targets)
                    if isinstance(field_set, field_set_type):
                        nfpm_package_targets.append(cast(tgt, NfpmPackageTarget))
                    break
            if identified_target:
                continue

            for field_set_type in package_field_set_types:
                if field_set_type.is_applicable(tgt):
                    identified_target = True
                    package_targets.append(tgt)
                    break
            if identified_target:
                continue

            remaining_targets.append(tgt)

        return cls(
            nfpm_content_targets=tuple(nfpm_content_targets),
            nfpm_package_targets=tuple(nfpm_package_targets),
            package_targets=tuple(package_targets),
            remaining_targets=tuple(remaining_targets),
        )


class NfpmPackagingSandboxRequest:
    field_set: NfpmPackageFieldSet
    transitive_targets: TransitiveTargets


@dataclass(frozen=True)
class NfpmPackagingSandbox:
    digest: Digest


@rule
async def populate_nfpm_packaging_sandbox(
    request: NfpmPackagingSandboxRequest, union_membership: UnionMembership
) -> NfpmPackagingSandbox:
    deps = _NfpmSortedDeps.sort(request.field_set, request.transitive_targets, union_membership)

    # Build packages for deps that are Packages
    package_field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, deps.package_targets)
    )
    packages = await MultiGet(
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in package_field_sets_per_target.field_sets
    )

    # hydrate any other source files

    # Modify the sources snapshot to handle relocations

    sandbox_digest = await Get(
        Digest,
        MergeDigests(
            [
                *(package.digest for package in packages),
            ]
        ),
    )

    return NfpmPackagingSandbox(sandbox_digest)


def rules():
    return [*collect_rules()]
