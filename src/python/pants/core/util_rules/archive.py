# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.util_rules import system_binaries
from pants.core.util_rules.system_binaries import SEARCH_PATHS
from pants.core.util_rules.system_binaries import ArchiveFormat as ArchiveFormat
from pants.core.util_rules.system_binaries import (
    GunzipBinary,
    GunzipBinaryRequest,
    TarBinary,
    TarBinaryRequest,
    UnzipBinary,
    UnzipBinaryRequest,
    ZipBinary,
    ZipBinaryRequest,
)
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel


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
        zip_binary = await Get(ZipBinary, ZipBinaryRequest())
        argv = zip_binary.create_archive_argv(request.output_filename, request.snapshot.files)
        env = {}
        input_digest = request.snapshot.digest
    else:
        tar_binary = await Get(TarBinary, TarBinaryRequest())
        argv = tar_binary.create_archive_argv(
            request.output_filename, request.snapshot.files, request.format
        )
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


@dataclass(frozen=True)
class MaybeExtractArchiveRequest:
    """A request to extract a single archive file (otherwise returns the input digest).

    :param digest: The digest of the archive to maybe extract. If the archive contains a single file
        which matches a known suffix, the `ExtractedArchive` will contain the extracted digest.
        Otherwise the `ExtractedArchive` will contain this digest.
    :param use_suffix: If provided, extracts the single file archive as if it had this suffix.
        Useful in situations where the file is archived then renamed.
        (E.g. A Python `.whl` is a renamed `.zip`, so the client should provide `".zip"`)
    """

    digest: Digest
    use_suffix: str | None = None


@dataclass(frozen=True)
class ExtractedArchive:
    """The result of extracting an archive."""

    digest: Digest


@rule
async def convert_digest_to_MaybeExtractArchiveRequest(
    digest: Digest,
) -> MaybeExtractArchiveRequest:
    """Backwards-compatibility helper."""
    return MaybeExtractArchiveRequest(digest)


@rule(desc="Extracting an archive file", level=LogLevel.DEBUG)
async def maybe_extract_archive(request: MaybeExtractArchiveRequest) -> ExtractedArchive:
    """If digest contains a single archive file, extract it, otherwise return the input digest."""
    extract_archive_dir = "__extract_archive_dir"
    snapshot, output_dir_digest = await MultiGet(
        Get(Snapshot, Digest, request.digest),
        Get(Digest, CreateDigest([Directory(extract_archive_dir)])),
    )
    if len(snapshot.files) != 1:
        return ExtractedArchive(request.digest)

    archive_path = snapshot.files[0]
    archive_suffix = request.use_suffix or "".join(PurePath(archive_path).suffixes)
    is_zip = archive_suffix.endswith(".zip")
    is_tar = archive_suffix.endswith(
        (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar.lz4")
    )
    is_gz = not is_tar and archive_suffix.endswith(".gz")
    if not is_zip and not is_tar and not is_gz:
        return ExtractedArchive(request.digest)

    merge_digest_get = Get(Digest, MergeDigests((request.digest, output_dir_digest)))
    if is_zip:
        input_digest, unzip_binary = await MultiGet(
            merge_digest_get,
            Get(UnzipBinary, UnzipBinaryRequest()),
        )
        argv = unzip_binary.extract_archive_argv(archive_path, extract_archive_dir)
        env = {}
    elif is_tar:
        input_digest, tar_binary = await MultiGet(
            merge_digest_get,
            Get(TarBinary, TarBinaryRequest()),
        )
        argv = tar_binary.extract_archive_argv(
            archive_path, extract_archive_dir, archive_suffix=archive_suffix
        )
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}
    else:
        input_digest, gunzip = await MultiGet(
            merge_digest_get,
            Get(GunzipBinary, GunzipBinaryRequest()),
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
    resulting_digest = await Get(Digest, RemovePrefix(result.output_digest, extract_archive_dir))
    return ExtractedArchive(resulting_digest)


def rules():
    return (*collect_rules(), *system_binaries.rules())
