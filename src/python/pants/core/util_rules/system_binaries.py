# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
from typing import Sequence

from pants.engine import process
from pants.engine.internals.selectors import Get
from pants.engine.process import BinaryPath, BinaryPathRequest, BinaryPaths, BinaryPathTest
from pants.engine.rules import collect_rules, rule
from pants.python import binaries as python_binaries
from pants.python.binaries import PythonBinary
from pants.util.logging import LogLevel

# TODO: Should this be configurable?
SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


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
class Gunzip:
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
def prepare_gunzip(python: PythonBinary) -> Gunzip:
    return Gunzip(python)


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


# TODO(#12946): Get rid of this when it becomes possible to use `Get()` with only one arg.


class _ZipBinaryRequest:
    pass


class _UnzipBinaryRequest:
    pass


class _GunzipRequest:
    pass


class _TarBinaryRequest:
    pass


@rule
async def find_zip_wrapper(_: _ZipBinaryRequest, zip_binary: ZipBinary) -> ZipBinary:
    return zip_binary


@rule
async def find_unzip_wrapper(_: _UnzipBinaryRequest, unzip_binary: UnzipBinary) -> UnzipBinary:
    return unzip_binary


@rule
async def find_gunzip_wrapper(_: _GunzipRequest, gunzip: Gunzip) -> Gunzip:
    return gunzip


@rule
async def find_tar_wrapper(_: _TarBinaryRequest, tar_binary: TarBinary) -> TarBinary:
    return tar_binary


def rules():
    return [*collect_rules(), *python_binaries.rules(), *process.rules()]
