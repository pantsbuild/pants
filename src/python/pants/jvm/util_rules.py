# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pants.engine.fs import Digest, DigestContents, DigestSubset, FileDigest, PathGlobs
from pants.engine.rules import Get, collect_rules, rule


@dataclass(frozen=True)
class ExtractFileDigest:
    digest: Digest
    file_path: str


@rule
async def digest_to_file_digest(request: ExtractFileDigest) -> FileDigest:
    """TODO(#11806): This is just a workaround; this extraction should be provided directly by the engine."""

    digest = await Get(Digest, DigestSubset(request.digest, PathGlobs([request.file_path])))
    digest_contents = await Get(DigestContents, Digest, digest)
    if len(digest_contents) == 0:
        raise Exception(f"ExtractFileDigest: '{request.file_path}' not found in {request.digest}.")
    elif len(digest_contents) > 1:
        raise Exception(
            f"ExtractFileDigest: Unexpected error: '{request.file_path}' found multiple times in {request.digest}"
        )

    file_content = digest_contents[0]
    hasher = hashlib.sha256()
    hasher.update(file_content.content)
    return FileDigest(
        fingerprint=hasher.hexdigest(), serialized_bytes_length=len(file_content.content)
    )


def rules():
    return [*collect_rules()]
