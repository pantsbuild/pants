# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.nfpm.field_sets import NfpmRpmPackageFieldSet
from pants.backend.nfpm.fields.rpm import NfpmRpmDependsField, NfpmRpmProvidesField
from pants.backend.nfpm.native_libs.elfdeps.rules import RequestPexELFInfo, elfdeps_analyze_pex
from pants.backend.nfpm.native_libs.elfdeps.rules import rules as elfdeps_rules
from pants.backend.nfpm.util_rules.contents import (
    GetPackageFieldSetsForNfpmContentFileDepsRequest,
    get_package_field_sets_for_nfpm_content_file_deps,
)
from pants.backend.nfpm.util_rules.inject_config import (
    InjectedNfpmPackageFields,
    InjectNfpmPackageFieldsRequest,
)
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet, package_pex_binary
from pants.backend.python.util_rules.pex import Pex, create_pex
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.engine.addresses import Address
from pants.engine.internals.selectors import concurrently
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import Field, Target
from pants.engine.unions import UnionMembership, UnionRule


@dataclass(frozen=True)
class RpmDependsFromPexRequest:
    target_pex: Pex


@dataclass(frozen=True)
class RpmDependsInfo:
    provides: tuple[str, ...]
    requires: tuple[str, ...]


@rule
async def rpm_depends_from_pex(request: RpmDependsFromPexRequest) -> RpmDependsInfo:
    # This rule provides a platform-agnostic replacement for `rpmdeps` in native rpm builds.
    pex_elf_info = await elfdeps_analyze_pex(RequestPexELFInfo(request.target_pex), **implicitly())
    return RpmDependsInfo(
        provides=tuple(provided.so_info for provided in pex_elf_info.provides),
        requires=tuple(required.so_info for required in pex_elf_info.requires),
    )


async def _get_pex_deps_of_content_file_targets(
    address: Address, union_membership: UnionMembership
) -> tuple[Pex, ...]:
    """Get all pex_binary targets that are (transitive) deps of nfpm_content_file targets."""
    package_field_sets_for_nfpm_content_files = (
        await get_package_field_sets_for_nfpm_content_file_deps(
            GetPackageFieldSetsForNfpmContentFileDepsRequest([address], [PexBinaryFieldSet]),
            **implicitly(),
        )
    )
    pex_binary_field_sets = package_field_sets_for_nfpm_content_files.package_field_sets
    build_pex_requests = await concurrently(
        package_pex_binary(field_set, **implicitly())
        for field_set in pex_binary_field_sets.field_sets
    )
    pex_binaries = await concurrently(
        create_pex(**implicitly({pex_request.request: PexFromTargetsRequest}))
        for pex_request in build_pex_requests
    )
    return pex_binaries


class NativeLibsNfpmPackageFieldsRequest(InjectNfpmPackageFieldsRequest):
    # low priority to allow in-repo plugins to override/correct injected dependencies.
    priority = 2

    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return NfpmRpmPackageFieldSet.is_applicable(target)


@rule
async def inject_native_libs_dependencies_in_package_fields(
    request: NativeLibsNfpmPackageFieldsRequest,
    union_membership: UnionMembership,
) -> InjectedNfpmPackageFields:
    address = request.target.address

    fields: list[Field] = list(request.injected_fields.values())

    # TODO: support scanning more packaged binaries than just pex_binaries.

    pex_binaries = await _get_pex_deps_of_content_file_targets(address, union_membership)
    if not pex_binaries:
        return InjectedNfpmPackageFields(fields, address=address)

    if NfpmRpmPackageFieldSet.is_applicable(request.target):
        # This is like running rpmdeps -> elfdeps.
        rpm_depends_infos = await concurrently(
            rpm_depends_from_pex(RpmDependsFromPexRequest(pex)) for pex in pex_binaries
        )
        provides = list(request.get_field(NfpmRpmProvidesField).value or ())
        depends = list(request.get_field(NfpmRpmDependsField).value or ())
        for rpm_depends_info in rpm_depends_infos:
            provides.extend(rpm_depends_info.provides)
            depends.extend(rpm_depends_info.requires)
        fields.extend(
            [
                NfpmRpmProvidesField(provides, address=address),
                NfpmRpmDependsField(depends, address=address),
            ]
        )

    return InjectedNfpmPackageFields(fields, address=address)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *elfdeps_rules(),
        *collect_rules(),
        UnionRule(InjectNfpmPackageFieldsRequest, NativeLibsNfpmPackageFieldsRequest),
    )
