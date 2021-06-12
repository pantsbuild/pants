# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, Snapshot
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessResult,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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
    def extract_archive_argv(self, archive_path: str) -> tuple[str, ...]:
        # Note that the `output_dir` does not need to already exist.
        # The caller should validate that it's a valid `.zip` file.
        return (self.path, archive_path)


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

    def extract_archive_argv(self, archive_path: str) -> tuple[str, ...]:
        # Note that the `output_dir` must already exist.
        # The caller should validate that it's a valid `.tar` file.
        return (self.path, "xf", archive_path)


@rule(desc="Finding the `zip` binary", level=LogLevel.DEBUG)
async def find_zip() -> ZipBinary:
    request = BinaryPathRequest(
        binary_name="zip", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["-v"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError(request, rationale="create `.zip` archives")
    return ZipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `unzip` binary", level=LogLevel.DEBUG)
async def find_unzip() -> UnzipBinary:
    request = BinaryPathRequest(
        binary_name="unzip", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["-v"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError(request, rationale="download the tools Pants needs to run")
    return UnzipBinary(first_path.path, first_path.fingerprint)


@rule(desc="Finding the `tar` binary", level=LogLevel.DEBUG)
async def find_tar() -> TarBinary:
    request = BinaryPathRequest(
        binary_name="tar", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["--version"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError(request, rationale="download the tools Pants needs to run")
    return TarBinary(first_path.path, first_path.fingerprint)


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
async def create_archive(
    request: CreateArchive, tar_binary: TarBinary, zip_binary: ZipBinary
) -> Digest:
    if request.format == ArchiveFormat.ZIP:
        argv = zip_binary.create_archive_argv(request)
        env = {}
        input_digest = request.snapshot.digest
    else:
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
async def maybe_extract_archive(
    digest: Digest, tar_binary: TarBinary, unzip_binary: UnzipBinary
) -> ExtractedArchive:
    """If digest contains a single archive file, extract it, otherwise return the input digest."""
    extract_archive_dir = "__extract_archive_dir"
    snapshot, output_dir_digest = await MultiGet(
        Get(Snapshot, Digest, digest),
        Get(Digest, CreateDigest([Directory(extract_archive_dir)])),
    )
    if len(snapshot.files) != 1:
        return ExtractedArchive(digest)

    input_digest = await Get(Digest, MergeDigests((digest, output_dir_digest)))
    fp = snapshot.files[0]
    archive_path = f"../{fp}"
    if fp.endswith(".zip"):
        argv = unzip_binary.extract_archive_argv(archive_path)
        env = {}
    elif fp.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        argv = tar_binary.extract_archive_argv(archive_path)
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}
    else:
        return ExtractedArchive(digest)

    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            env=env,
            input_digest=input_digest,
            description=f"Extract {fp}",
            level=LogLevel.DEBUG,
            output_directories=(".",),
            working_directory=extract_archive_dir,
        ),
    )
    return ExtractedArchive(result.output_digest)


def rules():
    return collect_rules()
