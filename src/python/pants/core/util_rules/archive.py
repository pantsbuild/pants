# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.util_rules import system_binaries
from pants.core.util_rules.adhoc_binaries import GunzipBinary
from pants.core.util_rules.system_binaries import SEARCH_PATHS
from pants.core.util_rules.system_binaries import ArchiveFormat as ArchiveFormat
from pants.core.util_rules.system_binaries import BashBinary, TarBinary, UnzipBinary, ZipBinary
from pants.engine.fs import (
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


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
    # #16091 -- if an arg list is really long, archive utilities tend to get upset.
    # passing a list of filenames into the utilities fixes this.
    FILE_LIST_FILENAME = "__pants_archive_filelist__"
    file_list_file = FileContent(
        FILE_LIST_FILENAME, "\n".join(request.snapshot.files).encode("utf-8")
    )
    file_list_file_digest = await Get(Digest, CreateDigest([file_list_file]))
    files_digests = [file_list_file_digest, request.snapshot.digest]
    input_digests = []

    if request.format == ArchiveFormat.ZIP:
        zip_binary, bash_binary = await MultiGet(Get(ZipBinary), Get(BashBinary))
        env = {}
        argv: tuple[str, ...] = (
            bash_binary.path,
            "-c",
            softwrap(
                f"""
                {zip_binary.path} --names-stdin {shlex.quote(request.output_filename)}
                < {FILE_LIST_FILENAME}
                """
            ),
        )
    else:
        tar_binary = await Get(TarBinary)
        argv = tar_binary.create_archive_argv(
            request.output_filename,
            request.format,
            input_file_list_filename=FILE_LIST_FILENAME,
        )
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}

        # `tar` requires that the output filename's parent directory exists,so if the caller
        # wants the output in a directory we explicitly create it here.
        # We have to guard this path as the Rust code will crash if we give it empty paths.
        output_dir = os.path.dirname(request.output_filename)
        if output_dir != "":
            output_dir_digest = await Get(Digest, CreateDigest([Directory(output_dir)]))
            input_digests.append(output_dir_digest)

    input_digest = await Get(Digest, MergeDigests([*files_digests, *input_digests]))

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
    env = {}
    append_only_caches: FrozenDict[str, str] = FrozenDict({})
    if is_zip:
        input_digest, unzip_binary = await MultiGet(merge_digest_get, Get(UnzipBinary))
        argv = unzip_binary.extract_archive_argv(archive_path, extract_archive_dir)
    elif is_tar:
        input_digest, tar_binary = await MultiGet(merge_digest_get, Get(TarBinary))
        argv = tar_binary.extract_archive_argv(
            archive_path, extract_archive_dir, archive_suffix=archive_suffix
        )
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}
    else:
        input_digest, gunzip = await MultiGet(merge_digest_get, Get(GunzipBinary))
        argv = gunzip.extract_archive_argv(archive_path, extract_archive_dir)
        append_only_caches = gunzip.python_binary.APPEND_ONLY_CACHES

    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            env=env,
            input_digest=input_digest,
            description=f"Extract {archive_path}",
            level=LogLevel.DEBUG,
            output_directories=(extract_archive_dir,),
            append_only_caches=append_only_caches,
        ),
    )
    resulting_digest = await Get(Digest, RemovePrefix(result.output_digest, extract_archive_dir))
    return ExtractedArchive(resulting_digest)


def rules():
    return (*collect_rules(), *system_binaries.rules())
