# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import functools
import json
import logging
import posixpath
import re
import textwrap
import urllib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import TypedDict, TypeVar, cast

from packaging.version import InvalidVersion

from pants.backend.python.providers.python_build_standalone.constraints import (
    ConstraintParseError,
    ConstraintSatisfied,
    ConstraintsList,
)
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
from pants.option.errors import OptionsError
from pants.option.global_options import NamedCachesDirOption
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.resources import read_sibling_resource
from pants.util.strutil import softwrap
from pants.version import Version

logger = logging.getLogger(__name__)

PBS_SANDBOX_NAME = ".python_build_standalone"
PBS_NAMED_CACHE_NAME = "python_build_standalone"
PBS_APPEND_ONLY_CACHES = FrozenDict({PBS_NAMED_CACHE_NAME: PBS_SANDBOX_NAME})

_T = TypeVar("_T")  # Define type variable "T"


class PBSPythonInfo(TypedDict):
    url: str
    sha256: str
    size: int


PBSVersionsT = dict[str, dict[str, dict[str, PBSPythonInfo]]]


@dataclass
class _ParsedPBSPython:
    py_version: Version
    pbs_release_tag: Version
    platform: Platform
    url: str
    sha256: str
    size: int


def _parse_py_version_and_pbs_release_tag(
    version_and_tag: str,
) -> tuple[Version | None, Version | None]:
    version_and_tag = version_and_tag.strip()
    if not version_and_tag:
        return None, None

    parts = version_and_tag.split("+", 1)
    py_version: Version | None = None
    pbs_release_tag: Version | None = None

    if len(parts) >= 1:
        try:
            py_version = Version(parts[0])
        except InvalidVersion:
            raise ValueError(f"Version `{parts[0]}` is not a valid Python version.")

    if len(parts) == 2:
        try:
            pbs_release_tag = Version(parts[1])
        except InvalidVersion:
            raise ValueError(f"PBS release tag `{parts[1]}` is not a valid version.")

    return py_version, pbs_release_tag


def _parse_pbs_url(url: str) -> tuple[Version, Version, Platform]:
    parsed_url = urllib.parse.urlparse(urllib.parse.unquote(url))
    base_path = posixpath.basename(parsed_url.path)

    base_path_no_prefix = base_path.removeprefix("cpython-")
    if base_path_no_prefix == base_path:
        raise ValueError(
            f"Unable to parse the provided URL since it does not have a cpython prefix as per the PBS naming convention: {url}"
        )

    base_path_parts = base_path_no_prefix.split("-", 1)
    if len(base_path_parts) != 2:
        raise ValueError(
            f"Unable to parse the provided URL because it does not follow the PBS naming convention: {url}"
        )

    py_version, pbs_release_tag = _parse_py_version_and_pbs_release_tag(base_path_parts[0])
    if not py_version or not pbs_release_tag:
        raise ValueError(
            "Unable to parse the Python version and PBS release tag from the provided URL "
            f"because it does not follow the PBS naming convention: {url}"
        )

    platform: Platform
    match base_path_parts[1].split("-"):
        case [
            "x86_64" | "x86_64_v2" | "x86_64_v3" | "x86_64_v4",
            "unknown",
            "linux",
            "gnu" | "musl",
            *_,
        ]:
            platform = Platform.linux_x86_64
        case ["aarch64", "unknown", "linux", "gnu", *_]:
            platform = Platform.linux_arm64
        case ["x86_64", "apple", "darwin", *_]:
            platform = Platform.macos_x86_64
        case ["aarch64", "apple", "darwin", *_]:
            platform = Platform.macos_arm64
        case _:
            raise ValueError(
                "Unable to parse the platform from the provided URL "
                f"because it does not follow the PBS naming convention: {url}"
            )

    return py_version, pbs_release_tag, platform


def _parse_from_three_fields(parts: Sequence[str], orig_value: str) -> _ParsedPBSPython:
    assert len(parts) == 3
    sha256, size, url = parts

    try:
        py_version, pbs_release_tag, platform = _parse_pbs_url(url)
    except ValueError as e:
        raise ExternalToolError(
            f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
            f"the value `{orig_value}` could not be parsed: {e}"
        )

    return _ParsedPBSPython(
        py_version=py_version,
        pbs_release_tag=pbs_release_tag,
        platform=platform,
        url=url,
        sha256=sha256,
        size=int(size),
    )


def _parse_from_five_fields(parts: Sequence[str], orig_value: str) -> _ParsedPBSPython:
    assert len(parts) == 5
    py_version_and_tag_str, platform_str, sha256, filesize_str, url = (x.strip() for x in parts)

    try:
        maybe_py_version, maybe_pbs_release_tag = _parse_py_version_and_pbs_release_tag(
            py_version_and_tag_str
        )
    except ValueError:
        raise ExternalToolError(
            f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
            f"the value `{orig_value}` declares version `{py_version_and_tag_str}` in the first field, "
            "but it could not be parsed as a PBS release version."
        )

    maybe_platform: Platform | None = None
    if not platform_str:
        pass
    elif platform_str in (
        Platform.linux_x86_64.value,
        Platform.linux_arm64.value,
        Platform.macos_x86_64.value,
        Platform.macos_arm64.value,
    ):
        maybe_platform = Platform(platform_str)
    else:
        raise ExternalToolError(
            f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
            f"the value `{orig_value}` declares platforn `{platform_str}` in the second field, "
            "but that value is not a known Pants platform. It must be one of "
            "`linux_x86_64`, `linux_arm64`, `macos_x86_64`, or `macos_arm64`."
        )

    if len(sha256) != 64 or not re.match("^[a-zA-Z0-9]+$", sha256):
        raise ExternalToolError(
            f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
            f"the value `{orig_value}` declares SHA256 checksum `{sha256}` in the third field, "
            "but that value does not parse as a SHA256 checksum."
        )

    try:
        filesize: int = int(filesize_str)
    except ValueError:
        raise ExternalToolError(
            f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
            f"the value `{orig_value}` declares file size `{filesize_str}` in the fourth field, "
            "but that value does not parse as an integer."
        )

    maybe_inferred_py_version: Version | None = None
    maybe_inferred_pbs_release_tag: Version | None = None
    maybe_inferred_platform: Platform | None = None
    try:
        (
            maybe_inferred_py_version,
            maybe_inferred_pbs_release_tag,
            maybe_inferred_platform,
        ) = _parse_pbs_url(url)
    except ValueError:
        pass

    def _validate_inferred(
        *, explicit: _T | None, inferred: _T | None, description: str, field_pos: str
    ) -> _T:
        if explicit is None:
            if inferred is None:
                raise ExternalToolError(
                    f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
                    f"the value `{orig_value}` does not declare a {description} in the {field_pos} field, and no {description} "
                    "could be inferred from the URL."
                )
            else:
                return inferred
        else:
            if inferred is not None and explicit != inferred:
                logger.warning(
                    f"While parsing the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option, "
                    f"the value `{orig_value}` declares {description} `{explicit}` in the {field_pos} field, but Pants inferred "
                    f"{description} `{inferred}` from the URL."
                )
            return explicit

    maybe_py_version = _validate_inferred(
        explicit=maybe_py_version,
        inferred=maybe_inferred_py_version,
        description="version",
        field_pos="first",
    )

    maybe_pbs_release_tag = _validate_inferred(
        explicit=maybe_pbs_release_tag,
        inferred=maybe_inferred_pbs_release_tag,
        description="PBS release tag",
        field_pos="first",
    )

    maybe_platform = _validate_inferred(
        explicit=maybe_platform,
        inferred=maybe_inferred_platform,
        description="platform",
        field_pos="second",
    )

    return _ParsedPBSPython(
        py_version=maybe_py_version,
        pbs_release_tag=maybe_pbs_release_tag,
        platform=maybe_platform,
        url=url,
        sha256=sha256,
        size=filesize,
    )


@functools.cache
def load_pbs_pythons() -> PBSVersionsT:
    versions_info = json.loads(read_sibling_resource(__name__, "versions_info.json"))
    pbs_release_metadata = versions_info["pythons"]
    return cast("PBSVersionsT", pbs_release_metadata)


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

            Each element is a pipe-separated string of either `py_version+pbs_release_tag|platform|sha256|length|url` or
            `sha256|length|url`, where:

            - `py_version` is the Python version string
            - `pbs_release_tag` is the PBS release tag (i.e., the PBS-specific version)
            - `platform` is one of `[{",".join(Platform.__members__.keys())}]`
            - `sha256` is the 64-character hex representation of the expected sha256
                digest of the download file, as emitted by `shasum -a 256`
            - `length` is the expected length of the download file in bytes, as emitted by
                `wc -c`
            - `url` is the download URL to the `.tar.gz` archive

            E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813|https://<URL>`
            or `https://<URL>|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.

            Values are space-stripped, so pipes can be indented for readability if necessary. If the three field
            format is used, then Pants will infer the `py_version`, `pbs_release_tag`, and `platform` fields from
            the URL. With the five field format, one or more of `py_version`, `pbs_release_tag`, and `platform`
            may be left blank if Pants can infer the field from the URL.

            Additionally, any versions you specify here will override the default Pants metadata for
            that version.
            """
        ),
    )

    _release_constraints = StrOption(
        default=None,
        help=textwrap.dedent(
            """
            Version constraints on the PBS "release" version to ensure only matching PBS releases are considered.
            Constraints should be specfied using operators like `>=`, `<=`, `>`, `<`, `==`, or `!=` in a similar
            manner to Python interpreter constraints: e.g., `>=20241201` or `>=20241201,<20250101`.
            """
        ),
    )

    @memoized_property
    def release_constraints(self) -> ConstraintsList:
        rcs = self._release_constraints
        if rcs is None or not rcs.strip():
            return ConstraintsList([])

        try:
            return ConstraintsList.parse(self._release_constraints or "")
        except ConstraintParseError as e:
            raise OptionsError(
                f"The `[{PBSPythonProviderSubsystem.options_scope}].release_constraints option` is not valid: {e}"
            ) from None

    def get_user_supplied_pbs_pythons(self) -> PBSVersionsT:
        user_supplied_pythons: dict[str, dict[str, dict[str, PBSPythonInfo]]] = {}

        for version_info in self.known_python_versions or []:
            version_parts = [x.strip() for x in version_info.split("|")]
            if len(version_parts) not in (3, 5):
                raise ExternalToolError(
                    f"Each value for the `[{PBSPythonProviderSubsystem.options_scope}].known_python_versions` option "
                    "must be a set of three or five values separated by `|` characters as follows:\n\n"
                    "- 3 fields: URL|SHA256|FILE_SIZE\n\n"
                    "- 5 fields: PYTHON_VERSION+PBS_RELEASE|PLATFORM|SHA256|FILE_SIZE|URL\n\n"
                    "\n\nIf 3 fields are provided, Pants will attempt to infer values based on the URL which must "
                    "follow the PBS naming conventions.\n\n"
                    f"Instead, the following value was provided: {version_info}"
                )

            info = (
                _parse_from_three_fields(version_parts, orig_value=version_info)
                if len(version_parts) == 3
                else _parse_from_five_fields(version_parts, orig_value=version_info)
            )

            py_version: str = str(info.py_version)
            pbs_release_tag: str = str(info.pbs_release_tag)

            if py_version not in user_supplied_pythons:
                user_supplied_pythons[py_version] = {}
            if pbs_release_tag not in user_supplied_pythons[py_version]:
                user_supplied_pythons[py_version][pbs_release_tag] = {}

            pbs_python_info = PBSPythonInfo(url=info.url, sha256=info.sha256, size=info.size)

            user_supplied_pythons[py_version][pbs_release_tag][
                info.platform.value
            ] = pbs_python_info

        return user_supplied_pythons

    def get_all_pbs_pythons(self) -> PBSVersionsT:
        all_pythons = load_pbs_pythons().copy()

        user_supplied_pythons: PBSVersionsT = self.get_user_supplied_pbs_pythons()

        for py_version, release_metadatas_for_py_version in user_supplied_pythons.items():
            for (
                release_tag,
                platform_metadata_for_releases,
            ) in release_metadatas_for_py_version.items():
                for platform_name, platform_metadata in platform_metadata_for_releases.items():
                    if py_version not in all_pythons:
                        all_pythons[py_version] = {}
                    if release_tag not in all_pythons[py_version]:
                        all_pythons[py_version][release_tag] = {}
                    all_pythons[py_version][release_tag][platform_name] = platform_metadata

        return all_pythons


class PBSPythonProvider(PythonProvider):
    pass


def _choose_python(
    interpreter_constraints: InterpreterConstraints,
    universe: Iterable[str],
    pbs_versions: Mapping[str, Mapping[str, Mapping[str, PBSPythonInfo]]],
    platform: Platform,
    release_constraints: ConstraintSatisfied,
) -> tuple[str, Version, PBSPythonInfo]:
    """Choose the highest supported patchlevel of the lowest supported major/minor version
    consistent with any PBS release constraint."""

    # Construct a list of candidate PBS releases.
    candidate_pbs_releases: list[tuple[tuple[int, int, int], Version, PBSPythonInfo]] = []
    supported_python_triplets = interpreter_constraints.enumerate_python_versions(universe)
    for triplet in supported_python_triplets:
        triplet_str = ".".join(map(str, triplet))
        pbs_version_metadata = pbs_versions.get(triplet_str)
        if not pbs_version_metadata:
            continue

        for tag, platform_metadata in pbs_version_metadata.items():
            if not release_constraints.is_satisified(Version(tag)):
                continue

            pbs_version_platform_metadata = platform_metadata.get(platform.value)
            if not pbs_version_platform_metadata:
                continue

            candidate_pbs_releases.append((triplet, Version(tag), pbs_version_platform_metadata))

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
    #
    # This also sorts by release tag in ascending order. So it chooses the highest available PBS
    # release for that chosen Python version.
    candidate_pbs_releases.sort(key=lambda x: (x[0], x[1]))
    for i, (py_version_triplet, pbs_version, metadata) in enumerate(candidate_pbs_releases):
        if (
            # Last candidate, we're good!
            i == len(candidate_pbs_releases) - 1
            # Next candidate is the next major/minor version, so this is the highest patchlevel.
            or candidate_pbs_releases[i + 1][0][0:2] != py_version_triplet[0:2]
        ):
            return (".".join(map(str, py_version_triplet)), pbs_version, metadata)

    raise AssertionError("The loop should have returned the final item.")


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

    python_version, _pbs_version, pbs_py_info = _choose_python(
        request.interpreter_constraints,
        python_setup.interpreter_versions_universe,
        versions_info,
        platform,
        pbs_subsystem.release_constraints,
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
