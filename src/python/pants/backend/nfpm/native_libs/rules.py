# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.nfpm.field_sets import NfpmDebPackageFieldSet, NfpmRpmPackageFieldSet
from pants.backend.nfpm.fields.all import NfpmArchField
from pants.backend.nfpm.fields.deb import NfpmDebDependsField
from pants.backend.nfpm.fields.rpm import NfpmRpmDependsField, NfpmRpmProvidesField
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

from .deb.rules import DebSearchForSonamesRequest, deb_search_for_sonames
from .deb.rules import rules as deb_rules
from .deb.utils import shlibdeps_filter_sonames
from .elfdeps.rules import RequestPexELFInfo, elfdeps_analyze_pex_wheels
from .elfdeps.rules import rules as elfdeps_rules
from .target_types import DebDistroCodenameField, DebDistroField
from .target_types import rules as target_types_rules


@dataclass(frozen=True)
class DebDependsFromPexRequest:
    target_pex: Pex
    distro: str
    distro_codename: str
    debian_arch: str


@dataclass(frozen=True)
class DebDependsInfo:
    requires: tuple[str, ...]


@rule
async def deb_depends_from_pex(request: DebDependsFromPexRequest) -> DebDependsInfo:
    # This rule partially replaces `dh_shlibdeps` + `dpkg-shlibdeps` in native deb builds.
    # `dpkg-shlibdeps` calculates deps that replace ${shlibs:<dep field>} vars in debian/control files.
    #   - By default, `dpkg-shlibdeps` puts the package deps in ${shlibs:Depends}.
    #   - When building an "Essential" package, it puts the deps in ${shlibs:Pre-Depends} instead.
    #   - If requested, some deps can also go in ${shlibs:Recommends} or ${shilbs:Suggests}.
    # This rule only calculates one list of deps (the equivalent of ${shlibs:Depends}).
    # Consuming rules are responsible for putting these deps in one or more nfpm package dep field(s).

    pex_elf_info = await elfdeps_analyze_pex_wheels(
        RequestPexELFInfo(request.target_pex), **implicitly()
    )

    sonames = shlibdeps_filter_sonames(so_info.soname for so_info in pex_elf_info.requires)

    packages_for_sonames = await deb_search_for_sonames(
        DebSearchForSonamesRequest(
            request.distro,
            request.distro_codename,
            request.debian_arch,
            sonames,
            from_best_so_files=True,
        )
    )

    # this blindly grabs all of them, but we really need to select only one so_file per soname and use those packages
    package_deps = {
        package
        for packages_for_soname in packages_for_sonames.packages_for_sonames
        for packages_per_so_file in packages_for_soname.packages_per_so_files
        for package in packages_per_so_file.packages
    }
    # TODO: Should there be a minimum version constraint for libc.so.6 based on so_info.version?
    return DebDependsInfo(requires=tuple(sorted(package_deps)))


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
    pex_elf_info = await elfdeps_analyze_pex_wheels(
        RequestPexELFInfo(request.target_pex), **implicitly()
    )
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
        return any(
            field_set_type.is_applicable(target)
            for field_set_type in (NfpmDebPackageFieldSet, NfpmRpmPackageFieldSet)
        )


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

    if NfpmDebPackageFieldSet.is_applicable(request.target):
        # This is like running deb helper shlib-deps.
        deb_depends_infos = await concurrently(
            deb_depends_from_pex(
                DebDependsFromPexRequest(
                    pex,
                    request.get_field(DebDistroField).value or "",
                    request.get_field(DebDistroCodenameField).value or "",
                    request.get_field(NfpmArchField).value or "",
                )
            )
            for pex in pex_binaries
        )
        depends = list(request.get_field(NfpmDebDependsField).value or ())
        for deb_depends_info in deb_depends_infos:
            depends.extend(deb_depends_info.requires)
        fields.append(NfpmDebDependsField(depends, address=address))

    elif NfpmRpmPackageFieldSet.is_applicable(request.target):
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
        *deb_rules(),
        *elfdeps_rules(),
        *target_types_rules(),
        *collect_rules(),
        UnionRule(InjectNfpmPackageFieldsRequest, NativeLibsNfpmPackageFieldsRequest),
    )
