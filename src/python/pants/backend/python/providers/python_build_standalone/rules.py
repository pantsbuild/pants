# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import functools
import json
import operator
import textwrap
import uuid
from pathlib import PurePath
from typing import Callable, Iterable, Mapping, TypedDict, cast

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
from pants.core.util_rules.system_binaries import (
    CpBinary,
    MkdirBinary,
    MvBinary,
    RmBinary,
    ShBinary,
    TestBinary,
)
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.errors import ConfigError
from pants.option.global_options import NamedCachesDirOption
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_sibling_resource
from pants.util.strutil import softwrap
from pants.version import Version

PBS_SANDBOX_NAME = ".python_build_standalone"
PBS_NAMED_CACHE_NAME = "python_build_standalone"
PBS_APPEND_ONLY_CACHES = FrozenDict({PBS_NAMED_CACHE_NAME: PBS_SANDBOX_NAME})


class PBSPythonInfo(TypedDict):
    url: str
    sha256: str
    size: int
    tag: str


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
        under `python_build_standalone/<version>`. Wiping the relevant version directory
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

    _release_constraint = StrOption(
        default=None,
        help=textwrap.dedent(
            """
            A constraint on the PBS "release" version to ensure only matching PBS releases are considered.
            """
        ),
    )

    def get_all_pbs_pythons(self) -> dict[str, dict[str, PBSPythonInfo]]:
        all_pythons = load_pbs_pythons().copy()

        for version_info in self.known_python_versions or []:
            try:
                pyversion, platform, sha256, filesize, url = (
                    x.strip() for x in version_info.split("|")
                )
            except ValueError:
                raise ExternalToolError(
                    f"Bad value for [{PBSPythonProviderSubsystem.options_scope}].known_python_versions: {version_info}"
                )

            if pyversion not in all_pythons:
                all_pythons[pyversion] = {}

            all_pythons[pyversion][platform] = PBSPythonInfo(
                url=url, sha256=sha256, size=int(filesize), tag="99999999"
            )

        return all_pythons

    def make_release_constraint_evaluator(self) -> Callable[[Version], bool]:
        rc = self._release_constraint
        if rc is None:
            return lambda _version: True

        operators = (
            (">=", operator.ge),
            ("<=", operator.le),
            ("==", operator.eq),
            ("!=", operator.ne),
            # `>` and `<` must come last!
            (">", operator.gt),
            ("<", operator.lt),
        )
        cmp_op_and_callback: tuple[str, Callable[[Version, Version], bool]] | None = None
        for op, callback in operators:
            if rc.startswith(op):
                cmp_op_and_callback = (op, cast("Callable[[Version, Version], bool]", callback))
                break

        if cmp_op_and_callback is None:
            raise ConfigError(
                "release_constraint must start with a comparison operator, i.e. >=, <=, ==, !=, <, >"
            )

        cmp_op, cmp_callback = cmp_op_and_callback
        cmp_version = Version(rc[len(cmp_op) :])

        def callback_func(version: Version) -> bool:
            nonlocal cmp_callback, cmp_version
            return cmp_callback(version, cmp_version)

        return callback_func


class PBSPythonProvider(PythonProvider):
    pass


def _choose_python(
    interpreter_constraints: InterpreterConstraints,
    universe: Iterable[str],
    pbs_versions: Mapping[str, Mapping[str, PBSPythonInfo]],
    platform: Platform,
    release_constraint_func: Callable[[Version], bool],
) -> tuple[str, PBSPythonInfo]:
    """Choose the highest supported patchlevel of the lowest supported major/minor version
    consistent with any PBS release constraint."""

    # Construct a list of candidate PBS releases.
    candidate_pbs_releases: list[tuple[tuple[int, int, int], PBSPythonInfo]] = []
    supported_python_triplets = interpreter_constraints.enumerate_python_versions(universe)
    for triplet in supported_python_triplets:
        triplet_str = ".".join(map(str, triplet))
        pbs_version_metadata = pbs_versions.get(triplet_str)
        if not pbs_version_metadata:
            continue

        pbs_version_platform_metadata = pbs_version_metadata.get(platform.value)
        if not pbs_version_platform_metadata:
            continue

        tag_as_version = Version(pbs_version_platform_metadata["tag"])
        if not release_constraint_func(tag_as_version):
            continue

        candidate_pbs_releases.append((triplet, pbs_version_platform_metadata))

    if not candidate_pbs_releases:
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

    # Choose the highest supported patchlevel of the lowest supported major/minor version
    # by searching until the major/minor version increases or the search ends (in which case the
    # last candidate is the one).
    candidate_pbs_releases.sort(key=lambda x: x[0])
    major_minor = candidate_pbs_releases[0][0][0:2]
    i = 0
    while i < len(candidate_pbs_releases):
        if (
            i + 1 < len(candidate_pbs_releases)
            and candidate_pbs_releases[i + 1][0][0:2] != major_minor
        ):
            r = candidate_pbs_releases[i]
            return (".".join(map(str, r[0])), r[1])
        i += 1

    r = candidate_pbs_releases[-1]
    return (".".join(map(str, r[0])), r[1])


@rule
async def get_python(
    request: PBSPythonProvider,
    python_setup: PythonSetup,
    pbs_subsystem: PBSPythonProviderSubsystem,
    platform: Platform,
    named_caches_dir: NamedCachesDirOption,
    sh: ShBinary,
    mkdir: MkdirBinary,
    cp: CpBinary,
    mv: MvBinary,
    rm: RmBinary,
    test: TestBinary,
) -> PythonExecutable:
    versions_info = pbs_subsystem.get_all_pbs_pythons()

    python_version, pbs_py_info = _choose_python(
        request.interpreter_constraints,
        python_setup.interpreter_versions_universe,
        versions_info,
        platform,
        pbs_subsystem.make_release_constraint_evaluator(),
    )

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

    sandbox_cache_dir = PurePath(PBS_SANDBOX_NAME)

    # The final desired destination within the named cache:
    persisted_destination = sandbox_cache_dir / python_version

    # Temporary directory (on the same filesystem as the persisted destination) to copy to,
    # incorporating uniqueness so that we don't collide with concurrent invocations
    temp_dir = sandbox_cache_dir / "tmp" / f"pbs-copier-{uuid.uuid4()}"
    copy_target = temp_dir / python_version

    await Get(
        ProcessResult,
        Process(
            [
                sh.path,
                "-euc",
                # Atomically-copy the downloaded files into the named cache, in 5 steps:
                #
                # 1. Check if the target directory already exists, skipping all the work if it does
                #    (the atomic creation means this will be fully created by an earlier execution,
                #    no torn state).
                #
                # 2. Copy the files into a temporary directory within the persistent named cache. Copying
                #    into a temporary directory ensures that we don't end up with partial state if this
                #    process is interrupted. Placing the temporary directory within the persistent named
                #    cache ensures it is on the same filesystem as the final destination, allowing for
                #    atomic mv.
                #
                # 3. Actually move the temporary directory to the final destination, failing if it
                #    already exists (which would indicate a concurrent execution), but squashing that
                #    error. Note that this is specifically moving to the parent directory of the target,
                #    i.e. something like:
                #
                #        mv .python_build_standalone/tmp/pbs-copier-.../3.10.11 .python_build_standalone
                #
                #    which detects `.python_build_standalone` is a directory and thus attempts to create
                #    `.python_build_standalone/3.10.11`. This fails if that target already exists. The
                #    alternative of explicitly passing the final target like
                #    `mv ... .python_build_standalone/3.10.11` will (incorrectly) create nested
                #    directory `.python_build_standalone/3.10.11/3.10.11` if the target already exists.
                #
                # 4. Check it worked. In particular, mv might fail for a different reason than the final
                #    destination already existing: in those cases, we won't have put things in the right
                #    place, and downstream code won't have the Python it needs. So, we check that the
                #    final destination exists and fail if it doesn't, surfacing any errors to the user.
                #
                # 5. Clean-up the temporary files
                f"""
                # Step 1: check and skip
                if {test.path} -d {persisted_destination}; then
                    echo "{persisted_destination} already exists, fully created by earlier execution" >&2
                    exit 0
                fi

                # Step 2: copy from the digest into the named cache
                {mkdir.path} -p "{temp_dir}"
                {cp.path} -R python "{copy_target}"

                # Step 3: attempt to move, squashing the error
                {mv.path} "{copy_target}" "{persisted_destination.parent}" || echo "mv failed: $?" >&2

                # Step 4: confirm and clean-up
                if ! {test.path} -d "{persisted_destination}"; then
                    echo "Failed to create {persisted_destination}" >&2
                    exit 1
                fi

                # Step 5: remove the temporary directory
                {rm.path} -rf "{temp_dir}"
                """,
            ],
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
        # One would normally set append_only_caches=PBS_APPEND_ONLY_CACHES
        # here, but it is already going to be injected into the pex
        # environment by PythonBuildStandaloneBinary
    )


def rules():
    return (
        *collect_rules(),
        *pex_rules(),
        *external_tools_rules(),
        UnionRule(PythonProvider, PBSPythonProvider),
    )
