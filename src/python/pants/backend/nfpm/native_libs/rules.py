# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import json
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
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


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *elfdeps_rules(),
        *collect_rules(),
    )
