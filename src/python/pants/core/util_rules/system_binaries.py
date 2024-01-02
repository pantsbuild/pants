# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent  # noqa: PNT20
from typing import Iterable, Mapping, Sequence

from typing_extensions import Self

from pants.core.subsystems import python_bootstrap
from pants.core.util_rules.environments import EnvironmentTarget
from pants.engine.collection import DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


class SystemBinariesSubsystem(Subsystem):
    options_scope = "system-binaries"
    help = "System binaries related settings."

    class EnvironmentAware(Subsystem.EnvironmentAware):
        env_vars_used_by_options = ("PATH",)

        _DEFAULT_SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin")

        _system_binary_paths = StrListOption(
            default=[*_DEFAULT_SEARCH_PATHS],
            help=softwrap(
                """
                The PATH value that will searched for executables.

                The special string `"<PATH>"` will expand to the contents of the PATH env var.
                """
            ),
        )

        @memoized_property
        def system_binary_paths(self) -> SearchPath:
            def iter_path_entries():
                for entry in self._system_binary_paths:
                    if entry == "<PATH>":
                        path = self._options_env.get("PATH")
                        if path:
                            yield from path.split(os.pathsep)
                    else:
                        yield entry

            return SearchPath(iter_path_entries())


# -------------------------------------------------------------------------------------------
# `BinaryPath` types
# -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BinaryPath:
    path: str
    fingerprint: str

    def __init__(self, path: str, fingerprint: str | None = None) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self, "fingerprint", self._fingerprint() if fingerprint is None else fingerprint
        )

    @staticmethod
    def _fingerprint(content: bytes | bytearray | memoryview | None = None) -> str:
        hasher = hashlib.sha256() if content is None else hashlib.sha256(content)
        return hasher.hexdigest()

    @classmethod
    def fingerprinted(
        cls, path: str, representative_content: bytes | bytearray | memoryview
    ) -> Self:
        return cls(path, fingerprint=cls._fingerprint(representative_content))


@dataclass(unsafe_hash=True)
class BinaryPathTest:
    args: tuple[str, ...]
    fingerprint_stdout: bool

    def __init__(self, args: Iterable[str], fingerprint_stdout: bool = True) -> None:
        object.__setattr__(self, "args", tuple(args))
        object.__setattr__(self, "fingerprint_stdout", fingerprint_stdout)


class SearchPath(DeduplicatedCollection[str]):
    """The search path for binaries; i.e.: the $PATH."""


@dataclass(unsafe_hash=True)
class BinaryPathRequest:
    """Request to find a binary of a given name.

    If `check_file_entries` is `True` a BinaryPathRequest will consider any entries in the
    `search_path` that are file paths in addition to traditional directory paths.

    If a `test` is specified all binaries that are found will be executed with the test args and
    only those binaries whose test executions exit with return code 0 will be retained.
    Additionally, if test execution includes stdout content, that will be used to fingerprint the
    binary path so that upgrades and downgrades can be detected. A reasonable test for many programs
    might be `BinaryPathTest(args=["--version"])` since it will both ensure the program runs and
    also produce stdout text that changes upon upgrade or downgrade of the binary at the discovered
    path.
    """

    search_path: SearchPath
    binary_name: str
    check_file_entries: bool
    test: BinaryPathTest | None

    def __init__(
        self,
        *,
        search_path: Iterable[str],
        binary_name: str,
        check_file_entries: bool = False,
        test: BinaryPathTest | None = None,
    ) -> None:
        object.__setattr__(self, "search_path", SearchPath(search_path))
        object.__setattr__(self, "binary_name", binary_name)
        object.__setattr__(self, "check_file_entries", check_file_entries)
        object.__setattr__(self, "test", test)


@dataclass(frozen=True)
class BinaryPaths(EngineAwareReturnType):
    binary_name: str
    paths: tuple[BinaryPath, ...]

    def __init__(self, binary_name: str, paths: Iterable[BinaryPath] | None = None):
        object.__setattr__(self, "binary_name", binary_name)
        object.__setattr__(self, "paths", tuple(OrderedSet(paths) if paths else ()))

    def message(self) -> str:
        if not self.paths:
            return f"failed to find {self.binary_name}"
        found_msg = f"found {self.binary_name} at {self.paths[0]}"
        if len(self.paths) > 1:
            found_msg = f"{found_msg} and {pluralize(len(self.paths) - 1, 'other location')}"
        return found_msg

    @property
    def first_path(self) -> BinaryPath | None:
        """Return the first path to the binary that was discovered, if any."""
        return next(iter(self.paths), None)

    def first_path_or_raise(self, request: BinaryPathRequest, *, rationale: str) -> BinaryPath:
        """Return the first path to the binary that was discovered, if any."""
        first_path = self.first_path
        if not first_path:
            raise BinaryNotFoundError.from_request(request, rationale=rationale)
        return first_path


class BinaryNotFoundError(EnvironmentError):
    @classmethod
    def from_request(
        cls,
        request: BinaryPathRequest,
        *,
        rationale: str | None = None,
        alternative_solution: str | None = None,
    ) -> BinaryNotFoundError:
        """When no binary is found via `BinaryPaths`, and it is not recoverable.

        :param rationale: A short description of why this binary is needed, e.g.
            "download the tools Pants needs" or "run Python programs".
        :param alternative_solution: A description of what else users can do to fix the issue,
            beyond installing the program. For example, "Alternatively, you can set the option
            `--python-bootstrap-search-path` to change the paths searched."
        """
        msg = softwrap(
            f"""
            Cannot find `{request.binary_name}` on `{sorted(request.search_path)}`.
            Please ensure that it is installed
            """
        )
        msg += f" so that Pants can {rationale}." if rationale else "."
        if alternative_solution:
            msg += f"\n\n{alternative_solution}"
        return BinaryNotFoundError(msg)


# -------------------------------------------------------------------------------------------
# Binary shims
# Creates a Digest with a shim for each requested binary in a directory suitable for PATH.
# -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BinaryShimsRequest:
    """Request to create shims for one or more system binaries."""

    rationale: str = dataclasses.field(compare=False)

    # Create shims for provided binary paths
    paths: tuple[BinaryPath, ...] = tuple()

    # Create shims for the provided binary names after looking up the paths.
    requests: tuple[BinaryPathRequest, ...] = tuple()

    @classmethod
    def for_binaries(
        cls, *names: str, rationale: str, search_path: Sequence[str]
    ) -> BinaryShimsRequest:
        return cls(
            requests=tuple(
                BinaryPathRequest(binary_name=binary_name, search_path=search_path)
                for binary_name in names
            ),
            rationale=rationale,
        )

    @classmethod
    def for_paths(
        cls,
        *paths: BinaryPath,
        rationale: str,
    ) -> BinaryShimsRequest:
        return cls(
            paths=paths,
            rationale=rationale,
        )


@dataclass(frozen=True)
class BinaryShims:
    """The shims created for a BinaryShimsRequest is placed in `bin_directory` of the `digest`.

    The purpose of these shims is so that a Process may be executed with `immutable_input_digests`
    provided to the `Process`, and `path_component` included in its `PATH` environment variable.

    The alternative is to add the directories hosting the binaries directly, but that opens up for
    many more unrelated binaries to also be executable from PATH, leaking into the sandbox
    unnecessarily.
    """

    digest: Digest
    cache_name: str

    @property
    def immutable_input_digests(self) -> Mapping[str, Digest]:
        return FrozenDict({self.cache_name: self.digest})

    @property
    def path_component(self) -> str:
        return os.path.join("{chroot}", self.cache_name)


# -------------------------------------------------------------------------------------------
# Binaries
# -------------------------------------------------------------------------------------------


class BashBinary(BinaryPath):
    """The `bash` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))


# Note that updating this will impact the `archive` target defined in `core/target_types.py`.
class ArchiveFormat(Enum):
    TAR = "tar"
    TGZ = "tar.gz"
    TBZ2 = "tar.bz2"
    TXZ = "tar.xz"
    ZIP = "zip"


class ZipBinary(BinaryPath):
    def create_archive_argv(
        self, output_filename: str, input_files: Sequence[str]
    ) -> tuple[str, ...]:
        return (self.path, output_filename, *input_files)


class UnzipBinary(BinaryPath):
    def extract_archive_argv(self, archive_path: str, extract_path: str) -> tuple[str, ...]:
        # Note that the `output_dir` does not need to already exist.
        # The caller should validate that it's a valid `.zip` file.
        return (self.path, archive_path, "-d", extract_path)


@dataclass(frozen=True)
class TarBinary(BinaryPath):
    platform: Platform

    def create_archive_argv(
        self,
        output_filename: str,
        tar_format: ArchiveFormat,
        *,
        input_files: Sequence[str] = (),
        input_file_list_filename: str | None = None,
    ) -> tuple[str, ...]:
        # Note that the parent directory for the output_filename must already exist.
        #
        # We do not use `-a` (auto-set compression) because it does not work with older tar
        # versions. Not all tar implementations will support these compression formats - in that
        # case, the user will need to choose a different format.
        compression = {ArchiveFormat.TGZ: "z", ArchiveFormat.TBZ2: "j", ArchiveFormat.TXZ: "J"}.get(
            tar_format, ""
        )

        files_from = ("--files-from", input_file_list_filename) if input_file_list_filename else ()
        return (self.path, f"c{compression}f", output_filename, *input_files) + files_from

    def extract_archive_argv(
        self, archive_path: str, extract_path: str, *, archive_suffix: str
    ) -> tuple[str, ...]:
        # Note that the `output_dir` must already exist.
        # The caller should validate that it's a valid `.tar` file.
        prog_args = (
            ("-Ilz4",) if archive_suffix == ".tar.lz4" and not self.platform.is_macos else ()
        )
        return (self.path, *prog_args, "-xf", archive_path, "-C", extract_path)


class AwkBinary(BinaryPath):
    pass


class Base64Binary(BinaryPath):
    pass


class BasenameBinary(BinaryPath):
    pass


class Bzip2Binary(BinaryPath):
    pass


class Bzip3Binary(BinaryPath):
    pass


class CatBinary(BinaryPath):
    pass


class ChmodBinary(BinaryPath):
    pass


class CksumBinary(BinaryPath):
    pass


class CpBinary(BinaryPath):
    pass


class CutBinary(BinaryPath):
    pass


class DateBinary(BinaryPath):
    pass


class DdBinary(BinaryPath):
    pass


class DfBinary(BinaryPath):
    pass


class DiffBinary(BinaryPath):
    pass


class DirnameBinary(BinaryPath):
    pass


class DuBinary(BinaryPath):
    pass


class ExprBinary(BinaryPath):
    pass


class FindBinary(BinaryPath):
    pass


class GpgBinary(BinaryPath):
    pass


class GzipBinary(BinaryPath):
    pass


class HeadBinary(BinaryPath):
    pass


class IdBinary(BinaryPath):
    pass


class LnBinary(BinaryPath):
    pass


class Lz4Binary(BinaryPath):
    pass


class LzopBinary(BinaryPath):
    pass


class Md5sumBinary(BinaryPath):
    pass


class MkdirBinary(BinaryPath):
    pass


class MktempBinary(BinaryPath):
    pass


class MvBinary(BinaryPath):
    pass


class OpenBinary(BinaryPath):
    pass


class PwdBinary(BinaryPath):
    pass


class ReadlinkBinary(BinaryPath):
    pass


class RmBinary(BinaryPath):
    pass


class SedBinary(BinaryPath):
    pass


class ShBinary(BinaryPath):
    pass


class ShasumBinary(BinaryPath):
    pass


class SortBinary(BinaryPath):
    pass


class TailBinary(BinaryPath):
    pass


class TestBinary(BinaryPath):
    pass


class TouchBinary(BinaryPath):
    pass


class TrBinary(BinaryPath):
    pass


class WcBinary(BinaryPath):
    pass


class XargsBinary(BinaryPath):
    pass


class XzBinary(BinaryPath):
    pass


class ZstdBinary(BinaryPath):
    pass


class GitBinaryException(Exception):
    pass


class GitBinary(BinaryPath):
    def _invoke_unsandboxed(self, cmd: list[str]) -> str:
        """Invoke the given git command, _without_ the sandboxing provided by the `Process` API.

        This API is for internal use only: users should prefer to consume methods of the
        `GitWorktree` class.
        """
        cmd = [self.path, *cmd]

        self._log_call(cmd)

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            # Binary DNE or is not executable
            cmd_str = " ".join(cmd)
            raise GitBinaryException(f"Failed to execute command {cmd_str}: {e!r}")
        out, err = process.communicate()

        self._check_result(cmd, process.returncode, err.decode())

        return out.decode().strip()

    def _check_result(
        self, cmd: Iterable[str], result: int, failure_msg: str | None = None
    ) -> None:
        if result != 0:
            cmd_str = " ".join(cmd)
            raise GitBinaryException(failure_msg or f"{cmd_str} failed with exit code {result}")

    def _log_call(self, cmd: Iterable[str]) -> None:
        logger.debug("Executing: " + " ".join(cmd))


# -------------------------------------------------------------------------------------------
# Binaries Rules
# -------------------------------------------------------------------------------------------


@rule
async def create_binary_shims(
    binary_shims_request: BinaryShimsRequest,
    bash: BashBinary,
) -> BinaryShims:
    """Creates a bin directory with shims for all requested binaries.

    This can be provided to a `Process` as an `immutable_input_digest`, or can be merged into the
    input digest.
    """

    paths = binary_shims_request.paths
    requests = binary_shims_request.requests
    if requests:
        all_binary_paths = await MultiGet(
            Get(BinaryPaths, BinaryPathRequest, request) for request in requests
        )
        first_paths = tuple(
            binary_paths.first_path_or_raise(request, rationale=binary_shims_request.rationale)
            for binary_paths, request in zip(all_binary_paths, requests)
        )
        paths += first_paths

    scripts = [
        FileContent(
            os.path.basename(path.path), _create_shim(bash.path, path.path), is_executable=True
        )
        for path in paths
    ]

    digest = await Get(Digest, CreateDigest(scripts))
    cache_name = f"_binary_shims_{digest.fingerprint}"

    return BinaryShims(digest, cache_name)


def _create_shim(bash: str, binary: str) -> bytes:
    """The binary shim script to be placed in the output directory for the digest."""
    return dedent(
        f"""\
        #!{bash}
        exec "{binary}" "$@"
        """
    ).encode()


@rule(desc="Finding the `bash` binary", level=LogLevel.DEBUG)
async def get_bash(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> BashBinary:
    search_path = system_binaries.system_binary_paths

    request = BinaryPathRequest(
        binary_name="bash",
        search_path=search_path,
        test=BinaryPathTest(args=["--version"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError.from_request(request)
    return BashBinary(first_path.path, first_path.fingerprint)


@rule
async def find_binary(
    request: BinaryPathRequest,
    env_target: EnvironmentTarget,
) -> BinaryPaths:
    # If we are not already locating bash, recurse to locate bash to use it as an absolute path in
    # our shebang. This avoids mixing locations that we would search for bash into the search paths
    # of the request we are servicing.
    # TODO(#10769): Replace this script with a statically linked native binary so we don't
    #  depend on either /bin/bash being available on the Process host.
    if request.binary_name == "bash":
        shebang = "#!/usr/bin/env bash"
    else:
        bash = await Get(BashBinary)
        shebang = f"#!{bash.path}"

    script_path = "./find_binary.sh"
    script_header = dedent(
        f"""\
        {shebang}

        set -euox pipefail

        CHECK_FILE_ENTRIES={'1' if request.check_file_entries else ''}
        """
    )
    script_body = dedent(
        """\
        for path in ${PATH//:/ }; do
            if [[ -d "${path}" ]]; then
                # Handle traditional directory PATH element.
                maybe_exe="${path}/$1"
            elif [[ -n "${CHECK_FILE_ENTRIES}" ]]; then
                # Handle PATH elements that are filenames to allow for precise selection.
                maybe_exe="${path}"
            else
                maybe_exe=
            fi
            if [[ "$1" == "${maybe_exe##*/}" && -f "${maybe_exe}" && -x "${maybe_exe}" ]]
            then
                echo "${maybe_exe}"
            fi
        done
        """
    )
    script_content = script_header + script_body
    script_digest = await Get(
        Digest,
        CreateDigest([FileContent(script_path, script_content.encode(), is_executable=True)]),
    )

    # Some subtle notes about executing this script:
    #
    #  - We run the script with `ProcessResult` instead of `FallibleProcessResult` so that we
    #      can catch bugs in the script itself, given an earlier silent failure.
    search_path = os.pathsep.join(request.search_path)
    result = await Get(
        ProcessResult,
        Process(
            description=f"Searching for `{request.binary_name}` on PATH={search_path}",
            level=LogLevel.DEBUG,
            input_digest=script_digest,
            argv=[script_path, request.binary_name],
            env={"PATH": search_path},
            cache_scope=env_target.executable_search_path_cache_scope(),
        ),
    )

    binary_paths = BinaryPaths(binary_name=request.binary_name)
    found_paths = result.stdout.decode().splitlines()
    if not request.test:
        return dataclasses.replace(binary_paths, paths=[BinaryPath(path) for path in found_paths])

    results = await MultiGet(
        Get(
            FallibleProcessResult,
            Process(
                description=f"Test binary {path}.",
                level=LogLevel.DEBUG,
                argv=[path, *request.test.args],
                # NB: Since a failure is a valid result for this script, we always cache it,
                # regardless of success or failure.
                cache_scope=env_target.executable_search_path_cache_scope(cache_failures=True),
            ),
        )
        for path in found_paths
    )
    return dataclasses.replace(
        binary_paths,
        paths=[
            (
                BinaryPath.fingerprinted(path, result.stdout)
                if request.test.fingerprint_stdout
                else BinaryPath(path, result.stdout.decode())
            )
            for path, result in zip(found_paths, results)
            if result.exit_code == 0
        ],
    )


@rule(desc="Finding the `awk` binary", level=LogLevel.DEBUG)
async def find_awk(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> AwkBinary:
    request = BinaryPathRequest(binary_name="awk", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="awk file")
    return AwkBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `base64` binary", level=LogLevel.DEBUG)
async def find_base64(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Base64Binary:
    request = BinaryPathRequest(
        binary_name="base64", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="base64 file")
    return Base64Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `basename` binary", level=LogLevel.DEBUG)
async def find_basename(
    system_binaries: SystemBinariesSubsystem.EnvironmentAware,
) -> BasenameBinary:
    request = BinaryPathRequest(
        binary_name="basename", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="basename file")
    return BasenameBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `bzip2` binary", level=LogLevel.DEBUG)
async def find_bzip2(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Bzip2Binary:
    request = BinaryPathRequest(
        binary_name="bzip2", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="bzip2 file")
    return Bzip2Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `bzip3` binary", level=LogLevel.DEBUG)
async def find_bzip3(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Bzip3Binary:
    request = BinaryPathRequest(
        binary_name="bzip3", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="bzip3 file")
    return Bzip3Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cat` binary", level=LogLevel.DEBUG)
async def find_cat(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> CatBinary:
    request = BinaryPathRequest(binary_name="cat", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="outputing content from files")
    return CatBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `chmod` binary", level=LogLevel.DEBUG)
async def find_chmod(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ChmodBinary:
    request = BinaryPathRequest(
        binary_name="chmod", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(
        request, rationale="change file modes or Access Control Lists"
    )
    return ChmodBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cksum` binary", level=LogLevel.DEBUG)
async def find_cksum(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> CksumBinary:
    request = BinaryPathRequest(
        binary_name="cksum", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="cksum file")
    return CksumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cp` binary", level=LogLevel.DEBUG)
async def find_cp(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> CpBinary:
    request = BinaryPathRequest(binary_name="cp", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="copy files")
    return CpBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `cut` binary", level=LogLevel.DEBUG)
async def find_cut(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> CutBinary:
    request = BinaryPathRequest(binary_name="cut", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="cut file")
    return CutBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `date` binary", level=LogLevel.DEBUG)
async def find_date(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DateBinary:
    request = BinaryPathRequest(binary_name="date", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="date file")
    return DateBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `dd` binary", level=LogLevel.DEBUG)
async def find_dd(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DdBinary:
    request = BinaryPathRequest(binary_name="dd", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="dd file")
    return DdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `df` binary", level=LogLevel.DEBUG)
async def find_df(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DfBinary:
    request = BinaryPathRequest(binary_name="df", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="df file")
    return DfBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `diff` binary", level=LogLevel.DEBUG)
async def find_diff(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DiffBinary:
    request = BinaryPathRequest(binary_name="diff", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="compare files line by line")
    return DiffBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `dirname` binary", level=LogLevel.DEBUG)
async def find_dirname(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DirnameBinary:
    request = BinaryPathRequest(
        binary_name="dirname", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="dirname file")
    return DirnameBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `du` binary", level=LogLevel.DEBUG)
async def find_du(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> DuBinary:
    request = BinaryPathRequest(binary_name="du", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="du file")
    return DuBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `expr` binary", level=LogLevel.DEBUG)
async def find_expr(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ExprBinary:
    request = BinaryPathRequest(binary_name="expr", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="expr file")
    return ExprBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `find` binary", level=LogLevel.DEBUG)
async def find_find(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> FindBinary:
    request = BinaryPathRequest(binary_name="find", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="find file")
    return FindBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `git` binary", level=LogLevel.DEBUG)
async def find_git(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> GitBinary:
    request = BinaryPathRequest(binary_name="git", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(
        request, rationale="track changes to files in your build environment"
    )
    return GitBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `gpg` binary", level=LogLevel.DEBUG)
async def find_gpg(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> GpgBinary:
    request = BinaryPathRequest(binary_name="gpg", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="gpg file")
    return GpgBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `gzip` binary", level=LogLevel.DEBUG)
async def find_gzip(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> GzipBinary:
    request = BinaryPathRequest(binary_name="gzip", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="gzip file")
    return GzipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `head` binary", level=LogLevel.DEBUG)
async def find_head(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> HeadBinary:
    request = BinaryPathRequest(binary_name="head", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="head file")
    return HeadBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `id` binary", level=LogLevel.DEBUG)
async def find_id(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> IdBinary:
    request = BinaryPathRequest(binary_name="id", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="id file")
    return IdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `ln` binary", level=LogLevel.DEBUG)
async def find_ln(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> LnBinary:
    request = BinaryPathRequest(binary_name="ln", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="link files")
    return LnBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `lz4` binary", level=LogLevel.DEBUG)
async def find_lz4(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Lz4Binary:
    request = BinaryPathRequest(binary_name="lz4", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="lz4 file")
    return Lz4Binary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `lzop` binary", level=LogLevel.DEBUG)
async def find_lzop(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> LzopBinary:
    request = BinaryPathRequest(binary_name="lzop", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="lzop file")
    return LzopBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `md5sum` binary", level=LogLevel.DEBUG)
async def find_md5sum(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> Md5sumBinary:
    request = BinaryPathRequest(
        binary_name="md5sum", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="md5sum file")
    return Md5sumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `mkdir` binary", level=LogLevel.DEBUG)
async def find_mkdir(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> MkdirBinary:
    request = BinaryPathRequest(
        binary_name="mkdir", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="create directories")
    return MkdirBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `mktempt` binary", level=LogLevel.DEBUG)
async def find_mktemp(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> MktempBinary:
    request = BinaryPathRequest(
        binary_name="mktemp", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="create temporary files/directories")
    return MktempBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `mv` binary", level=LogLevel.DEBUG)
async def find_mv(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> MvBinary:
    request = BinaryPathRequest(binary_name="mv", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="move files")
    return MvBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `open` binary", level=LogLevel.DEBUG)
async def find_open(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> OpenBinary:
    request = BinaryPathRequest(binary_name="open", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="open URLs with default browser")
    return OpenBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `pwd` binary", level=LogLevel.DEBUG)
async def find_pwd(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> PwdBinary:
    request = BinaryPathRequest(binary_name="pwd", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="pwd file")
    return PwdBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `readlink` binary", level=LogLevel.DEBUG)
async def find_readlink(
    system_binaries: SystemBinariesSubsystem.EnvironmentAware,
) -> ReadlinkBinary:
    request = BinaryPathRequest(
        binary_name="readlink", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="defererence symlinks")
    return ReadlinkBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `rm` binary", level=LogLevel.DEBUG)
async def find_rm(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> RmBinary:
    request = BinaryPathRequest(binary_name="rm", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="rm file")
    return RmBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sed` binary", level=LogLevel.DEBUG)
async def find_sed(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> SedBinary:
    request = BinaryPathRequest(binary_name="sed", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sed file")
    return SedBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sh` binary", level=LogLevel.DEBUG)
async def find_sh(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ShBinary:
    request = BinaryPathRequest(binary_name="sh", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sh file")
    return ShBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `shasum` binary", level=LogLevel.DEBUG)
async def find_shasum(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ShasumBinary:
    request = BinaryPathRequest(
        binary_name="shasum", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="shasum file")
    return ShasumBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `sort` binary", level=LogLevel.DEBUG)
async def find_sort(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> SortBinary:
    request = BinaryPathRequest(binary_name="sort", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="sort file")
    return SortBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tail` binary", level=LogLevel.DEBUG)
async def find_tail(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TailBinary:
    request = BinaryPathRequest(binary_name="tail", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="tail file")
    return TailBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tar` binary", level=LogLevel.DEBUG)
async def find_tar(
    platform: Platform, system_binaries: SystemBinariesSubsystem.EnvironmentAware
) -> TarBinary:
    request = BinaryPathRequest(
        binary_name="tar",
        search_path=system_binaries.system_binary_paths,
        test=BinaryPathTest(args=["--version"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(
        request, rationale="download the tools Pants needs to run"
    )
    return TarBinary(first_path.path, first_path.fingerprint, platform)


@rule(desc="Finding the `test` binary", level=LogLevel.DEBUG)
async def find_test(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TestBinary:
    request = BinaryPathRequest(binary_name="test", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="test file")
    return TestBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `touch` binary", level=LogLevel.DEBUG)
async def find_touch(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TouchBinary:
    request = BinaryPathRequest(
        binary_name="touch", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="touch file")
    return TouchBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tr` binary", level=LogLevel.DEBUG)
async def find_tr(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> TrBinary:
    request = BinaryPathRequest(binary_name="tr", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="tr file")
    return TrBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `unzip` binary", level=LogLevel.DEBUG)
async def find_unzip(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> UnzipBinary:
    request = BinaryPathRequest(
        binary_name="unzip",
        search_path=system_binaries.system_binary_paths,
        test=BinaryPathTest(args=["-v"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(
        request, rationale="download the tools Pants needs to run"
    )
    return UnzipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `wc` binary", level=LogLevel.DEBUG)
async def find_wc(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> WcBinary:
    request = BinaryPathRequest(binary_name="wc", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="wc file")
    return WcBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `xargs` binary", level=LogLevel.DEBUG)
async def find_xargs(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> XargsBinary:
    request = BinaryPathRequest(
        binary_name="xargs", search_path=system_binaries.system_binary_paths
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="xargs file")
    return XargsBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `xz` binary", level=LogLevel.DEBUG)
async def find_xz(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> XzBinary:
    request = BinaryPathRequest(binary_name="xz", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="xz file")
    return XzBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `zip` binary", level=LogLevel.DEBUG)
async def find_zip(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ZipBinary:
    request = BinaryPathRequest(
        binary_name="zip",
        search_path=system_binaries.system_binary_paths,
        test=BinaryPathTest(args=["-v"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="create `.zip` archives")
    return ZipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `zstd` binary", level=LogLevel.DEBUG)
async def find_zstd(system_binaries: SystemBinariesSubsystem.EnvironmentAware) -> ZstdBinary:
    request = BinaryPathRequest(binary_name="zstd", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="zstd file")
    return ZstdBinary(first_path.path, first_path.fingerprint)


def rules():
    return [*collect_rules(), *python_bootstrap.rules()]


# -------------------------------------------------------------------------------------------
# Rules for fallible binaries
# -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MaybeGitBinary:
    git_binary: GitBinary | None = None


@rule(desc="Finding the `git` binary", level=LogLevel.DEBUG)
async def maybe_find_git(
    system_binaries: SystemBinariesSubsystem.EnvironmentAware,
) -> MaybeGitBinary:
    request = BinaryPathRequest(binary_name="git", search_path=system_binaries.system_binary_paths)
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        return MaybeGitBinary()

    return MaybeGitBinary(GitBinary(first_path.path, first_path.fingerprint))


class MaybeGitBinaryRequest:
    pass


@rule
async def maybe_find_git_wrapper(
    _: MaybeGitBinaryRequest, maybe_git_binary: MaybeGitBinary
) -> MaybeGitBinary:
    return maybe_git_binary
