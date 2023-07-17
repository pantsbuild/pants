# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import collections.abc
import functools
import json
import os
import textwrap
from typing import Iterable, TypedDict, cast

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PythonProvider
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolError,
    ExternalToolRequest,
)
from pants.core.util_rules.external_tool import rules as external_tools_rules
from pants.core.util_rules.system_binaries import CpBinary
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import NamedCachesDirOption
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_sibling_resource
from pants.util.strutil import softwrap

PBS_SANDBOX_NAME = ".python-build-standalone"
PBS_NAMED_CACHE_NAME = "python-build-standalone"
PBS_APPEND_ONLY_CACHES = FrozenDict({PBS_NAMED_CACHE_NAME: PBS_SANDBOX_NAME})


class PBSPythonInfo(TypedDict):
    url: str
    sha256: str
    size: int


@functools.cache
def load_pbs_pythons() -> dict[str, dict[str, PBSPythonInfo]]:
    return cast(
        "dict[str, dict[str, PBSPythonInfo]]",
        json.loads(read_sibling_resource(__name__, "versions_info.json"))["pythons"],
    )


class PBSPythonProviderSubsystem(Subsystem):
    options_scope = "python-build-standalone-python-provider"
    name = "python-build-standalone"
    help = softwrap(
        """
        A subsystem for Pants-provided Python leveraging Python Build Standalone (or PBS) (https://gregoryszorc.com/docs/python-build-standalone/main/).

        Enabling this subsystem will switch Pants from trying to find an appropriate Python on your
        system to using PBS to download the correct Python(s).

        The Pythons provided by PBS will be used to run any "user" code (your Python code as well
        as any Python-based tools you use, like black or pylint). The Pythons are also read-only to
        ensure they remain hermetic across runs of different tools and code.

        The Pythons themselves are stored in your `named_caches_dir`: https://www.pantsbuild.org/docs/reference-global#named_caches_dir
        under `python-build-standalone/<version>`. Wiping the relevant version directory
        (with `sudo rm -rf`) will force a re-download of Python.

        WARNING: PBS does have some behavior quirks, most notably that it has some hardcoded references
        to build-time paths (such as constants that are found in the `sysconfig` module). These paths
        may be used when trying to compile some extension modules from source.

        For more info, see https://gregoryszorc.com/docs/python-build-standalone/main/quirks.html.
        """
    )

    known_python_versions = StrListOption(
        default=None,
        default_help_repr=f"<Metadata for versions: {', '.join(sorted(load_pbs_pythons()))}>",
        advanced=True,
        help=textwrap.dedent(
            f"""
            Known versions to verify downloads against.

            Each element is a pipe-separated string of `version|platform|sha256|length|url`, where:

            - `version` is the version string
            - `platform` is one of `[{','.join(Platform.__members__.keys())}]`
            - `sha256` is the 64-character hex representation of the expected sha256
                digest of the download file, as emitted by `shasum -a 256`
            - `length` is the expected length of the download file in bytes, as emitted by
                `wc -c`
            - `url` is the download URL to the `.tar.gz` archive

            E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813|https://<URL>`.

            Values are space-stripped, so pipes can be indented for readability if necessary.

            Additionally, any versions you specify here will override the default Pants metadata for
            that version.
            """
        ),
    )

    def get_all_pbs_pythons(self) -> dict[str, dict[str, PBSPythonInfo]]:
        all_pythons = load_pbs_pythons().copy()

        for version_info in (self.known_python_versions or []):
            try:
                pyversion, platform, sha256, filesize, url = [
                    x.strip() for x in version_info.split("|")
                ]
            except ValueError:
                raise ExternalToolError(
                    f"Bad value for [{PBSPythonProviderSubsystem.options_scope}].known_python_versions: {version_info}"
                )

            if pyversion not in all_pythons:
                all_pythons[pyversion] = {}

            all_pythons[pyversion][platform] = PBSPythonInfo(
                url=url, sha256=sha256, size=int(filesize)
            )

        return all_pythons


class PBSPythonProvider(PythonProvider):
    pass


def _choose_python(
    interpreter_constraints: InterpreterConstraints,
    universe: Iterable[str],
    pbs_versions: collections.abc.Collection[str],
) -> str:
    """Choose the highest supported patch of the lowest supported Major/Minor version."""
    supported_python_triplets = interpreter_constraints.enumerate_python_versions(universe)
    version_triplet: tuple[int, int, int] | None = None
    for triplet in supported_python_triplets:
        pbs_supported_version = ".".join(map(str, triplet)) in pbs_versions
        if pbs_supported_version:
            if version_triplet and version_triplet[:2] < triplet[:2]:
                # This version is a major/minor above the previous supported one, we're done.
                break

            version_triplet = triplet

    if version_triplet is None:
        raise Exception(
            softwrap(
                f"""\
                Failed to find a supported Python Build Standalone for Interpreter Constraint: {interpreter_constraints.description}

                Supported versions are currently: {sorted(pbs_versions)}.

                You can teach Pants about newer Python versions supported by Python Build Standalone
                by setting the `known_python_versions` option in the {PBSPythonProviderSubsystem.name}
                subsystem. Run `{bin_name()} help-advanced {PBSPythonProviderSubsystem.options_scope}`
                for more info.
                """
            )
        )

    return ".".join(map(str, version_triplet))


@rule
async def get_python(
    request: PBSPythonProvider,
    python_setup: PythonSetup,
    pbs_subsystem: PBSPythonProviderSubsystem,
    platform: Platform,
    named_caches_dir: NamedCachesDirOption,
    cp: CpBinary,
) -> PythonExecutable:
    versions_info = pbs_subsystem.get_all_pbs_pythons()

    python_version = _choose_python(
        request.interpreter_constraints,
        python_setup.interpreter_versions_universe,
        versions_info,
    )
    pbs_py_info = versions_info[python_version][platform.value]

    downloaded_python = await Get(
        DownloadedExternalTool,
        ExternalToolRequest(
            DownloadFile(
                pbs_py_info["url"],
                FileDigest(
                    pbs_py_info["sha256"],
                    pbs_py_info["size"],
                ),
            ),
            "python/bin/python3",
        ),
    )

    await Get(
        ProcessResult,
        Process(
            [cp.path, "--recursive", "--no-clobber", "python", f"{PBS_SANDBOX_NAME}/{python_version}"],
            level=LogLevel.DEBUG,
            input_digest=downloaded_python.digest,
            description=f"Install Python {python_version}",
            append_only_caches=PBS_APPEND_ONLY_CACHES,
            # Don't cache, we want this to always be run so that we can assume for the rest of the
            # session the named_cache destination for this Python is valid, as the Python ecosystem
            # mainly assumes absolute paths for Python interpreters.
            cache_scope=ProcessCacheScope.PER_SESSION,
        ),
    )

    python_path = named_caches_dir.val / PBS_NAMED_CACHE_NAME / python_version / "bin" / "python3"
    return PythonExecutable(
        path=str(python_path),
        fingerprint=None,
        append_only_caches=PBS_APPEND_ONLY_CACHES,
    )


def rules():
    return (
        *collect_rules(),
        *pex_rules(),
        *external_tools_rules(),
        UnionRule(PythonProvider, PBSPythonProvider),
    )
