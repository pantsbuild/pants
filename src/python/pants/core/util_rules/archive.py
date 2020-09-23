# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Tuple

from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix, Snapshot
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


@dataclass(frozen=True)
class MaybeExtractable:
    """A newtype to work around rule graph resolution issues.

    Possibly https://github.com/pantsbuild/pants/issues/9320. Either way, we should fix the
    underlying issue and get rid of this type.
    """

    digest: Digest


@dataclass(frozen=True)
class ExtractedDigest:
    """The result of extracting an archive."""

    digest: Digest


# TODO: Should this be configurable?
SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


class UnzipBinary(BinaryPath):
    def extract_argv(self, *, archive_path: str, output_dir: str) -> Tuple[str, ...]:
        # Note that the `output_dir` does not need to already exist. The caller should also
        # validate that it's a valid `.zip` file.
        return (self.path, "-q", archive_path, "-d", output_dir)


@rule(level=LogLevel.DEBUG)
async def find_unzip() -> UnzipBinary:
    request = BinaryPathRequest(
        binary_name="unzip", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["-v"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError(request, rationale="download the tools Pants needs to run")
    return UnzipBinary(first_path.path, first_path.fingerprint)


class TarBinary(BinaryPath):
    def extract_argv(self, *, archive_path: str, output_dir: str) -> Tuple[str, ...]:
        # Note that the `output_dir` must already exist. The caller should also
        # validate that it's a valid `.tar` file.
        return (self.path, "xf", archive_path, "-C", output_dir)


@rule(level=LogLevel.DEBUG)
async def find_tar() -> TarBinary:
    request = BinaryPathRequest(
        binary_name="tar", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["--version"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError(request, rationale="download the tools Pants needs to run")
    return TarBinary(first_path.path, first_path.fingerprint)


@rule(level=LogLevel.DEBUG)
async def maybe_extract(
    extractable: MaybeExtractable, tar_binary: TarBinary, unzip_binary: UnzipBinary
) -> ExtractedDigest:
    """If digest contains a single archive file, extract it, otherwise return the input digest."""
    extractable_digest = extractable.digest
    output_dir = "out/"
    snapshot, output_dir_digest = await MultiGet(
        Get(Snapshot, Digest, extractable_digest),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )
    if len(snapshot.files) != 1:
        return ExtractedDigest(extractable_digest)

    input_digest = await Get(Digest, MergeDigests((extractable_digest, output_dir_digest)))
    fp = snapshot.files[0]
    if fp.endswith(".zip"):
        argv = unzip_binary.extract_argv(archive_path=fp, output_dir=output_dir)
        env = {}
    elif fp.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        argv = tar_binary.extract_argv(archive_path=fp, output_dir=output_dir)
        # `tar` expects to find a couple binaries like `gzip` and `xz` by looking on the PATH.
        env = {"PATH": os.pathsep.join(SEARCH_PATHS)}
    else:
        return ExtractedDigest(extractable_digest)

    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            env=env,
            input_digest=input_digest,
            description=f"Extract {fp}",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )
    strip_output_dir = await Get(Digest, RemovePrefix(result.output_digest, output_dir))
    return ExtractedDigest(strip_output_dir)


def rules():
    return collect_rules()
