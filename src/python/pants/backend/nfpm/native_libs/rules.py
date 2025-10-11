# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import json
import logging
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPexProcess, create_venv_pex
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, execute_process
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.init.import_util import find_matching_distributions
from pants.util.logging import LogLevel
from pants.util.resources import read_resource
from pants.version import VERSION

from .elfdeps.rules import RequestPexELFInfo, elfdeps_analyze_pex_wheels
from .elfdeps.rules import rules as elfdeps_rules

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
class DebPackagesForSoFile:
    so_file: str
    packages: tuple[str, ...]

    def __init__(self, so_file: str, packages: Iterable[str]):
        object.__setattr__(self, "so_file", so_file)
        object.__setattr__(self, "packages", tuple(sorted(packages)))


@dataclass(frozen=True)
class DebPackagesForSoname:
    soname: str
    packages_for_so_files: tuple[DebPackagesForSoFile, ...]

    def __init__(self, soname: str, packages_for_so_files: Iterable[DebPackagesForSoFile]):
        object.__setattr__(self, "soname", soname)
        object.__setattr__(self, "packages_for_so_files", tuple(packages_for_so_files))

    # TODO: method to select best so_file for a soname


@dataclass(frozen=True)
class DebPackagesForSonames:
    packages: tuple[DebPackagesForSoname, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Mapping[str, Iterable[str]]]) -> DebPackagesForSonames:
        return cls(
            tuple(
                DebPackagesForSoname(
                    soname,
                    (
                        DebPackagesForSoFile(so_file, packages)
                        for so_file, packages in files_to_packages.items()
                    ),
                )
                for soname, files_to_packages in raw.items()
            )
        )


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
                    f"--user-agent-suffix=pants/{VERSION}",
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
        logger.warning(result.stderr.decode("utf-8"))
        packages = {}

    return DebPackagesForSonames.from_dict(packages)


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

    # dpkg-shlibdeps ignores:
    #   - sonames that do not look like .so files
    #   - libm.so if libstdc++.so is already in deps
    # dpkg-shlibdeps can also exclude deps based on command line args.
    # Consuming rules are responsible for such exclusions, as this rule doesn't handle that.
    so_patt = re.compile(r"^.*\.so(\..*)?$")
    libm_patt = re.compile(r"^libm\.so\.\d+$")
    libstdcpp_patt = re.compile(r"^libstdc\+\+\.so\.\d+$")
    has_libstdcpp = any(libstdcpp_patt.match(so_info.soname) for so_info in pex_elf_info.requires)

    sonames = {
        so_info.soname
        for so_info in pex_elf_info.requires
        if so_patt.match(so_info.soname) and (not has_libstdcpp or libm_patt.match(so_info.soname))
    }

    packages_for_sonames = await deb_search_for_sonames(
        DebSearchForSonamesRequest(
            request.distro, request.distro_codename, request.debian_arch, sonames
        )
    )

    # this blindly grabs all of them, but we really need to select only one so_file per soname and use those packages
    package_deps = {
        package
        for packages_for_soname in packages_for_sonames.packages
        for packages_for_so_file in packages_for_soname.packages_for_so_files
        for package in packages_for_so_file.packages
    }
    # TODO: handle libc.so.6 dep resolution based on so_info.version?
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
        *elfdeps_rules(),
        *collect_rules(),
    )
