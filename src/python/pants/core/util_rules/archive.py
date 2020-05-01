# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.engine.fs import Digest, RemovePrefix, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get


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


def get_extraction_cmd(archive_path: str, output_dir: str) -> Optional[Tuple[str, ...]]:
    """Returns a shell command to run to extract the archive to the output directory."""
    # Note that we assume that mkdir, unzip, and tar exist in the executing environment.
    if archive_path.endswith(".zip"):
        return ("unzip", "-q", archive_path, "-d", output_dir)
    elif archive_path.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return ("mkdir", output_dir, "&&", "tar", "xf", archive_path, "-C", output_dir)
    return None


@rule
async def maybe_extract(extractable: MaybeExtractable) -> ExtractedDigest:
    """If digest contains a single archive file, extract it, otherwise return the input digest."""
    digest = extractable.digest
    snapshot = await Get[Snapshot](Digest, digest)
    if len(snapshot.files) == 1:
        output_dir = "out/"
        extraction_cmd = get_extraction_cmd(snapshot.files[0], output_dir)
        if extraction_cmd:
            extraction_cmd_str = " ".join(extraction_cmd)
            proc = Process(
                argv=("/bin/bash", "-c", f"{extraction_cmd_str}"),
                input_digest=digest,
                description=f"Extract {snapshot.files[0]}",
                env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
                output_directories=(output_dir,),
            )
            result = await Get[ProcessResult](Process, proc)
            strip_output_dir = await Get[Digest](RemovePrefix(result.output_digest, output_dir))
            return ExtractedDigest(strip_output_dir)
    return ExtractedDigest(digest)


def rules():
    return [maybe_extract, RootRule(MaybeExtractable)]
