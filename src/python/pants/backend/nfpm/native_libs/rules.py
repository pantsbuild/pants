# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import json
import logging
import sys
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
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPexProcess, create_pex, create_venv_pex
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, execute_process
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import Field, Target
from pants.engine.unions import UnionMembership, UnionRule
from pants.init.import_util import find_matching_distributions
from pants.util.logging import LogLevel
from pants.util.resources import read_resource

logger = logging.getLogger(__name__)

_SCRIPTS_PACKAGE = "pants.backend.nfpm.native_libs.scripts"
_DEB_SEARCH_FOR_SONAMES_SCRIPT = "deb_search_for_sonames.py"
_PEX_NAME = "native_libs_scripts.pex"


@dataclass(frozen=True)
class DebSearchForSonamesRequest:
    distro: str
    distro_codename: str
    debian_arch: str
    sonames: tuple[str, ...]

    def __init__(self, distro: str, distro_codename: str, debian_arch: str, sonames: Iterable[str]):
        object.__setattr__(self, "distro", distro)
        object.__setattr__(self, "distro_codename", distro_codename)
        object.__setattr__(self, "debian_arch", debian_arch)
        object.__setattr__(self, "sonames", tuple(sorted(sonames)))


@dataclass(frozen=True)
class DebPackagesForSonames:
    packages: tuple[str, ...]

    def __init__(self, packages: Iterable[str]):
        object.__setattr__(self, "packages", tuple(sorted(packages)))


@rule
async def deb_search_for_sonames(
    request: DebSearchForSonamesRequest,
) -> DebPackagesForSonames:
    script = read_resource(_SCRIPTS_PACKAGE, _DEB_SEARCH_FOR_SONAMES_SCRIPT)
    if not script:
        raise ValueError(
            f"Unable to find source of {_DEB_SEARCH_FOR_SONAMES_SCRIPT!r} in {_SCRIPTS_PACKAGE}"
        )

    script_content = FileContent(
        path=_DEB_SEARCH_FOR_SONAMES_SCRIPT, content=script, is_executable=True
    )

    # Pull python and requirements versions from the pants venv since that is what the script is tested with.
    pants_python = PythonExecutable.fingerprinted(
        sys.executable, ".".join(map(str, sys.version_info[:3])).encode("utf8")
    )
    distributions_in_pants_venv: list[importlib.metadata.Distribution] = list(
        find_matching_distributions(None)
    )
    constraints = tuple(f"{dist.name}=={dist.version}" for dist in distributions_in_pants_venv)
    requirements = {  # requirements (and transitive deps) are constrained to the versions in the pants venv
        "aiohttp",
        "beautifulsoup4",
    }

    script_digest, venv_pex = await concurrently(
        create_digest(CreateDigest([script_content])),
        create_venv_pex(
            **implicitly(
                PexRequest(
                    output_filename=_PEX_NAME,
                    internal_only=True,
                    python=pants_python,
                    requirements=PexRequirements(
                        requirements,
                        constraints_strings=constraints,
                        description_of_origin=f"Requirements for {_PEX_NAME}:{_DEB_SEARCH_FOR_SONAMES_SCRIPT}",
                    ),
                )
            )
        ),
    )

    result: FallibleProcessResult = await execute_process(
        **implicitly(
            VenvPexProcess(
                venv_pex,
                argv=(
                    script_content.path,
                    f"--distro={request.distro}",
                    f"--distro-codename={request.distro_codename}",
                    f"--arch={request.debian_arch}",
                    *request.sonames,
                ),
                input_digest=script_digest,
                description=f"Search deb packages for sonames: {request.sonames}",
                level=LogLevel.DEBUG,
            )
        )
    )

    if result.exit_code == 0:
        packages = json.loads(result.stdout)
    else:
        logger.warning(result.stderr)
        packages = ()

    return DebPackagesForSonames(packages)


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
