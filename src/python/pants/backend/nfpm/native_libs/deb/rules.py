# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import json
import logging
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import PurePath

from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import UnionRule
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, execute_process
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.init.import_util import find_matching_distributions
from pants.util.logging import LogLevel
from pants.util.resources import read_resource
from pants.version import VERSION

logger = logging.getLogger(__name__)

_NATIVE_LIBS_DEB_PACKAGE = "pants.backend.nfpm.native_libs.deb"
_SEARCH_FOR_SONAMES_SCRIPT = "search_for_sonames.py"
_PEX_NAME = "native_libs_deb.pex"


@dataclass(frozen=True)
class DebSearchForSonamesRequest:
    distro: str
    distro_codename: str
    debian_arch: str
    sonames: tuple[str, ...]
    from_best_so_files: bool

    def __init__(
        self,
        distro: str,
        distro_codename: str,
        debian_arch: str,
        sonames: Iterable[str],
        *,
        from_best_so_files: bool = False,
    ):
        object.__setattr__(self, "distro", distro)
        object.__setattr__(self, "distro_codename", distro_codename)
        object.__setattr__(self, "debian_arch", debian_arch)
        object.__setattr__(self, "sonames", tuple(sorted(sonames)))
        object.__setattr__(self, "from_best_so_files", from_best_so_files)


@dataclass(frozen=True)
class DebPackagesPerSoFile:
    so_file: str
    packages: tuple[str, ...]

    def __init__(self, so_file: str, packages: Iterable[str]):
        object.__setattr__(self, "so_file", so_file)
        object.__setattr__(self, "packages", tuple(sorted(packages)))


_TYPICAL_LD_PATH_PATTERNS = (
    # platform specific system libs (like libc) get selected first
    # "/usr/local/lib/*-linux-*/",
    "/lib/*-linux-*/",
    "/usr/lib/*-linux-*/",
    # Then look for a generic system libs
    # "/usr/local/lib/",
    "/lib/",
    "/usr/lib/",
    # Anything else has to be added manually to dependencies.
    # These rules cannot use symbols or shlibs metadata to inform package selection.
)


@dataclass(frozen=True)
class DebPackagesForSoname:
    soname: str
    packages_per_so_files: tuple[DebPackagesPerSoFile, ...]

    def __init__(self, soname: str, packages_per_so_files: Iterable[DebPackagesPerSoFile]):
        object.__setattr__(self, "soname", soname)
        object.__setattr__(self, "packages_per_so_files", tuple(packages_per_so_files))

    @property
    def from_best_so_files(self) -> DebPackagesForSoname:
        """Pick best so_files from packages_for_so_files using a simplified ld.so-like algorithm.

        The most preferred is first. This is NOT a recursive match; Only match if direct child of
        ld_path_patt dir. Anything that uses a subdir like /usr/lib/<app>/lib*.so.* uses rpath to
        prefer the app's libs over system libs. If this vastly simplified form of ld.so-style
        matching does not select the correct libs, then the package(s) that provide the shared lib
        should be added manually to the nfpm requires field.
        """
        if len(self.packages_per_so_files) <= 1:  # shortcut; no filtering required for 0-1 results.
            return self

        remaining = list(self.packages_per_so_files)

        packages_per_so_files = []
        for ld_path_patt in _TYPICAL_LD_PATH_PATTERNS:
            for packages_per_so_file in remaining[:]:
                if PurePath(packages_per_so_file.so_file).parent.match(ld_path_patt):
                    packages_per_so_files.append(packages_per_so_file)
                    remaining.remove(packages_per_so_file)

        return replace(self, packages_per_so_files=tuple(packages_per_so_files))


@dataclass(frozen=True)
class DebPackagesForSonames:
    packages_for_sonames: tuple[DebPackagesForSoname, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Mapping[str, Iterable[str]]]) -> DebPackagesForSonames:
        return cls(
            tuple(
                DebPackagesForSoname(
                    soname,
                    (
                        DebPackagesPerSoFile(so_file, packages)
                        for so_file, packages in files_to_packages.items()
                    ),
                )
                for soname, files_to_packages in raw.items()
            )
        )

    @property
    def from_best_so_files(self) -> DebPackagesForSonames:
        packages = []
        for packages_for_soname in self.packages_for_sonames:
            packages.append(packages_for_soname.from_best_so_files)
        return DebPackagesForSonames(tuple(packages))


@rule
async def deb_search_for_sonames(
    request: DebSearchForSonamesRequest,
) -> DebPackagesForSonames:
    script = read_resource(_NATIVE_LIBS_DEB_PACKAGE, _SEARCH_FOR_SONAMES_SCRIPT)
    if not script:
        raise ValueError(
            f"Unable to find source of {_SEARCH_FOR_SONAMES_SCRIPT!r} in {_NATIVE_LIBS_DEB_PACKAGE}"
        )

    script_content = FileContent(
        path=_SEARCH_FOR_SONAMES_SCRIPT, content=script, is_executable=True
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
        "aiohttp-retry",
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
                        description_of_origin=f"Requirements for {_PEX_NAME}:{_SEARCH_FOR_SONAMES_SCRIPT}",
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
        # The search API returns 200 even if no results were found.
        # A 4xx or 5xx error means we gave up retrying because the server is unavailable.
        # TODO: Should this raise an error instead of just a warning?
        logger.warning(result.stderr.decode("utf-8"))
        packages = {}

    deb_packages_for_sonames = DebPackagesForSonames.from_dict(packages)
    if request.from_best_so_files:
        return deb_packages_for_sonames.from_best_so_files
    return deb_packages_for_sonames


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
