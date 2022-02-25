# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
from typing import Sequence

from pants.core.subsystems import python_bootstrap
from pants.core.subsystems.python_bootstrap import PythonBootstrap
from pants.engine import process
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel

# TODO(#14492): This should be configurable via `[system-binaries]` subsystem, likely per-binary.
SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")

# -------------------------------------------------------------------------------------------
# Binaries
# -------------------------------------------------------------------------------------------


class PythonBinary(BinaryPath):
    """A Python3 interpreter for use by `@rule` code as an alternative to BashBinary scripts.

    Python is usable for `@rule` scripting independently of `pants.backend.python`, but currently
    thirdparty dependencies are not supported, because PEX lives in that backend.

    TODO: Consider extracting PEX out into the core in order to support thirdparty dependencies.
    """


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
class GunzipBinary:
    python: PythonBinary

    def extract_archive_argv(self, archive_path: str, extract_path: str) -> tuple[str, ...]:
        archive_name = os.path.basename(archive_path)
        dest_file_name = os.path.splitext(archive_name)[0]
        dest_path = os.path.join(extract_path, dest_file_name)
        script = dedent(
            f"""
            import gzip
            import shutil
            with gzip.GzipFile(filename={archive_path!r}, mode="rb") as source:
                with open({dest_path!r}, "wb") as dest:
                    shutil.copyfileobj(source, dest)
            """
        )
        return (self.python.path, "-c", script)


class TarBinary(BinaryPath):
    def create_archive_argv(
        self, output_filename: str, input_files: Sequence[str], tar_format: ArchiveFormat
    ) -> tuple[str, ...]:
        # Note that the parent directory for the output_filename must already exist.
        #
        # We do not use `-a` (auto-set compression) because it does not work with older tar
        # versions. Not all tar implementations will support these compression formats - in that
        # case, the user will need to choose a different format.
        compression = {ArchiveFormat.TGZ: "z", ArchiveFormat.TBZ2: "j", ArchiveFormat.TXZ: "J"}.get(
            tar_format, ""
        )
        return (self.path, f"c{compression}f", output_filename, *input_files)

    def extract_archive_argv(self, archive_path: str, extract_path: str) -> tuple[str, ...]:
        # Note that the `output_dir` must already exist.
        # The caller should validate that it's a valid `.tar` file.
        return (self.path, "xf", archive_path, "-C", extract_path)


# -------------------------------------------------------------------------------------------
# Rules to find binaries
# -------------------------------------------------------------------------------------------


@rule(desc="Finding a `python` binary", level=LogLevel.TRACE)
async def find_python(python_bootstrap: PythonBootstrap) -> PythonBinary:
    # PEX files are compatible with bootstrapping via Python 2.7 or Python 3.5+, but we select 3.6+
    # for maximum compatibility with internal scripts.
    interpreter_search_paths = python_bootstrap.interpreter_search_paths()
    all_python_binary_paths = await MultiGet(
        Get(
            BinaryPaths,
            BinaryPathRequest(
                search_path=interpreter_search_paths,
                binary_name=binary_name,
                check_file_entries=True,
                test=BinaryPathTest(
                    args=[
                        "-c",
                        # N.B.: The following code snippet must be compatible with Python 3.6+.
                        #
                        # We hash the underlying Python interpreter executable to ensure we detect
                        # changes in the real interpreter that might otherwise be masked by Pyenv
                        # shim scripts found on the search path. Naively, just printing out the full
                        # version_info would be enough, but that does not account for supported abi
                        # changes (e.g.: a pyenv switch from a py27mu interpreter to a py27m
                        # interpreter.)
                        #
                        # When hashing, we pick 8192 for efficiency of reads and fingerprint updates
                        # (writes) since it's a common OS buffer size and an even multiple of the
                        # hash block size.
                        dedent(
                            """\
                            import sys

                            major, minor = sys.version_info[:2]
                            if not (major == 3 and minor >= 6):
                                sys.exit(1)

                            import hashlib
                            hasher = hashlib.sha256()
                            with open(sys.executable, "rb") as fp:
                                for chunk in iter(lambda: fp.read(8192), b""):
                                    hasher.update(chunk)
                            sys.stdout.write(hasher.hexdigest())
                            """
                        ),
                    ],
                    fingerprint_stdout=False,  # We already emit a usable fingerprint to stdout.
                ),
            ),
        )
        for binary_name in python_bootstrap.interpreter_names
    )

    for binary_paths in all_python_binary_paths:
        path = binary_paths.first_path
        if path:
            return PythonBinary(
                path=path.path,
                fingerprint=path.fingerprint,
            )

    raise BinaryNotFoundError(
        "Was not able to locate a Python interpreter to execute rule code.\n"
        "Please ensure that Python is available in one of the locations identified by "
        "`[python-bootstrap] search_path`, which currently expands to:\n"
        f"  {interpreter_search_paths}"
    )


@rule(desc="Finding the `zip` binary", level=LogLevel.DEBUG)
async def find_zip() -> ZipBinary:
    request = BinaryPathRequest(
        binary_name="zip", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["-v"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="create `.zip` archives")
    return ZipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `unzip` binary", level=LogLevel.DEBUG)
async def find_unzip() -> UnzipBinary:
    request = BinaryPathRequest(
        binary_name="unzip", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["-v"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(
        request, rationale="download the tools Pants needs to run"
    )
    return UnzipBinary(first_path.path, first_path.fingerprint)


@rule
def find_gunzip(python: PythonBinary) -> GunzipBinary:
    return GunzipBinary(python)


@rule(desc="Finding the `tar` binary", level=LogLevel.DEBUG)
async def find_tar() -> TarBinary:
    request = BinaryPathRequest(
        binary_name="tar", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["--version"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(
        request, rationale="download the tools Pants needs to run"
    )
    return TarBinary(first_path.path, first_path.fingerprint)


# -------------------------------------------------------------------------------------------
# Rules for lazy requests
# TODO(#12946): Get rid of this when it becomes possible to use `Get()` with only one arg.
# -------------------------------------------------------------------------------------------


class ZipBinaryRequest:
    pass


class UnzipBinaryRequest:
    pass


class GunzipBinaryRequest:
    pass


class TarBinaryRequest:
    pass


@rule
async def find_zip_wrapper(_: ZipBinaryRequest, zip_binary: ZipBinary) -> ZipBinary:
    return zip_binary


@rule
async def find_unzip_wrapper(_: UnzipBinaryRequest, unzip_binary: UnzipBinary) -> UnzipBinary:
    return unzip_binary


@rule
async def find_gunzip_wrapper(_: GunzipBinaryRequest, gunzip: GunzipBinary) -> GunzipBinary:
    return gunzip


@rule
async def find_tar_wrapper(_: TarBinaryRequest, tar_binary: TarBinary) -> TarBinary:
    return tar_binary


def rules():
    return [*collect_rules(), *python_bootstrap.rules(), *process.rules()]
