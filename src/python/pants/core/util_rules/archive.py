# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent

from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix, Snapshot
from pants.engine.process import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessResult,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.python import binaries as python_binaries
from pants.python.binaries import PythonBinary
from pants.util.logging import LogLevel


# Note that updating this will impact the `archive` target defined in `core/target_types.py`.
class ArchiveFormat(Enum):
    TAR = "tar"
    TGZ = "tar.gz"
    TBZ2 = "tar.bz2"
    TXZ = "tar.xz"
    ZIP = "zip"


# -----------------------------------------------------------------------------------------------
# Find binaries to create/extract archives
# -----------------------------------------------------------------------------------------------

# TODO: Should this be configurable?
SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


class ZipBinary(BinaryPath):
    def create_archive_argv(self, request: CreateArchive) -> tuple[str, ...]:
        return (self.path, request.output_filename, *request.snapshot.files)


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
    def create_archive_argv(self, request: CreateArchive) -> tuple[str, ...]:
        # Note that the parent directory for the output_filename must already exist.
        #
        # We do not use `-a` (auto-set compression) because it does not work with older tar
        # versions. Not all tar implementations will support these compression formats - in that
        # case, the user will need to choose a different format.
        compression = {ArchiveFormat.TGZ: "z", ArchiveFormat.TBZ2: "j", ArchiveFormat.TXZ: "J"}.get(
            request.format, ""
        )
        return (self.path, f"c{compression}f", request.output_filename, *request.snapshot.files)

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


# -----------------------------------------------------------------------------------------------
# Create archives
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateArchive:
    """A request to create an archive.

    All files in the input snapshot will be included in the resulting archive.
    """

    snapshot: Snapshot
    output_filename: str
    format: ArchiveFormat


@rule(desc="Creating an archive file", level=LogLevel.DEBUG)
async def create_archive(request: CreateArchive) -> Digest:
    if request.format == ArchiveFormat.ZIP:
        zip_binary = await Get(ZipBinary, _ZipBinaryRequest())
        argv = zip_binary.create_archive_argv(request)
        env = {}
        input_digest = request.snapshot.digest
    else:
        tar_binary = await Get(TarBinary, _TarBinaryRequest())
        argv = tar_binary.create_archive_argv(request)
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}
        # `tar` requires that the output filename's parent directory exists.
        output_dir_digest = await Get(
            Digest, CreateDigest([Directory(os.path.dirname(request.output_filename))])
        )
        input_digest = await Get(Digest, MergeDigests([output_dir_digest, request.snapshot.digest]))

    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            env=env,
            input_digest=input_digest,
            description=f"Create {request.output_filename}",
            level=LogLevel.DEBUG,
            output_files=(request.output_filename,),
        ),
    )
    return result.output_digest


# -----------------------------------------------------------------------------------------------
# Extract archives
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedArchive:
    """The result of extracting an archive."""

    digest: Digest


@rule(desc="Extracting an archive file", level=LogLevel.DEBUG)
async def maybe_extract_archive(digest: Digest) -> ExtractedArchive:
    """If digest contains a single archive file, extract it, otherwise return the input digest."""
    extract_archive_dir = "__extract_archive_dir"
    snapshot, output_dir_digest = await MultiGet(
        Get(Snapshot, Digest, digest),
        Get(Digest, CreateDigest([Directory(extract_archive_dir)])),
    )
    if len(snapshot.files) != 1:
        return ExtractedArchive(digest)

    archive_path = snapshot.files[0]
    is_zip = archive_path.endswith(".zip")
    is_tar = archive_path.endswith(
        (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
    )
    is_gz = not is_tar and archive_path.endswith(".gz")
    if not is_zip and not is_tar and not is_gz:
        return ExtractedArchive(digest)

    merge_digest_get = Get(Digest, MergeDigests((digest, output_dir_digest)))
    if is_zip:
        input_digest, unzip_binary = await MultiGet(
            merge_digest_get,
            Get(UnzipBinary, _UnzipBinaryRequest()),
        )
        argv = unzip_binary.extract_archive_argv(archive_path, extract_archive_dir)
        env = {}
    elif is_tar:
        input_digest, tar_binary = await MultiGet(
            merge_digest_get,
            Get(TarBinary, _TarBinaryRequest()),
        )
        argv = tar_binary.extract_archive_argv(archive_path, extract_archive_dir)
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}
    else:
        input_digest, gunzip = await MultiGet(
            merge_digest_get,
            Get(Gunzip, _GunzipRequest()),
        )
        argv = gunzip.extract_archive_argv(archive_path, extract_archive_dir)
        env = {}

    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            env=env,
            input_digest=input_digest,
            description=f"Extract {archive_path}",
            level=LogLevel.DEBUG,
            output_directories=(extract_archive_dir,),
        ),
    )
    digest = await Get(Digest, RemovePrefix(result.output_digest, extract_archive_dir))
    return ExtractedArchive(digest)


def rules():
    return [
        *collect_rules(),
        *python_binaries.rules(),
    ]
