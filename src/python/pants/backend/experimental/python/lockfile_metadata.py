# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

BEGIN_LOCKFILE_HEADER = b"# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---"
END_LOCKFILE_HEADER = b"# --- END PANTS LOCKFILE METADATA ---"


@dataclass
class LockfileMetadata:
    invalidation_digest: str | None


# Lockfile metadata for headers
def lockfile_content_with_header(invalidation_digest: str, content: bytes) -> bytes:
    """Returns a version of the lockfile with a pants metadata header prepended."""
    return b"%b\n%b" % (lockfile_metadata_header(invalidation_digest), content)


def lockfile_metadata_header(invalidation_digest: str) -> bytes:
    """Produces a metadata bytes object for including at the top of a lockfile.

    Currently, this only consists of an invalidation digest for the file, which is used when Pants
    consumes the lockfile during builds.
    """
    return (
        b"""
%(BEGIN_LOCKFILE_HEADER)b
# invalidation digest: %(invalidation_digest)s
%(END_LOCKFILE_HEADER)b
    """
        % {
            b"BEGIN_LOCKFILE_HEADER": BEGIN_LOCKFILE_HEADER,
            b"invalidation_digest": invalidation_digest.encode("ascii"),
            b"END_LOCKFILE_HEADER": END_LOCKFILE_HEADER,
        }
    ).strip()


def read_lockfile_metadata(contents: bytes) -> LockfileMetadata:
    """Reads through `contents`, and returns the contents of the lockfile metadata block as a
    `LockfileMetadata` object."""

    metadata = {}

    in_metadata_block = False
    for line in contents.splitlines():
        line = line.strip()
        if line == BEGIN_LOCKFILE_HEADER:
            in_metadata_block = True
        elif line == END_LOCKFILE_HEADER:
            break
        elif in_metadata_block:
            key, value = (i.strip().decode("ascii") for i in line[1:].split(b":"))
            metadata[key] = value

    return LockfileMetadata(invalidation_digest=metadata.get("invalidation digest"))
