# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.util_rules.pex import Pex
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.unions import UnionRule

from .deb.rules import DebSearchForSonamesRequest, deb_search_for_sonames
from .deb.rules import rules as deb_rules
from .deb.utils import shlibdeps_filter_sonames
from .elfdeps.rules import RequestPexELFInfo, elfdeps_analyze_pex_wheels
from .elfdeps.rules import rules as elfdeps_rules
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


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *deb_rules(),
        *elfdeps_rules(),
        *target_types_rules(),
        *collect_rules(),
    )
