# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, TypeVar

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet

BEGIN_LOCKFILE_HEADER = b"# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---"
END_LOCKFILE_HEADER = b"# --- END PANTS LOCKFILE METADATA ---"


@dataclass
class LockfileMetadata:
    invalidation_digest: str | None
    valid_interpreter_constraints: InterpreterConstraints | None


def calculate_invalidation_digest(
    requirements: FrozenOrderedSet[str],
) -> str:
    """Returns an invalidation digest for the given requirements and interpreter constraints."""
    m = hashlib.sha256()
    pres = {
        "requirements": list(requirements),
    }
    m.update(json.dumps(pres).encode("utf-8"))
    return m.hexdigest()


def lockfile_content_with_header(
    regenerate_command: str,
    invalidation_digest: str,
    interpreter_constraints: InterpreterConstraints,
    content: bytes,
) -> bytes:
    """Returns a version of the lockfile with Pants metadata and usage instructions prepended."""
    regenerate_command = (
        f"# This lockfile was autogenerated by Pants. To regenerate, run:\n#\n"
        f"#    {regenerate_command}"
    )
    interpreter_constraints_str = [str(i) for i in interpreter_constraints]
    return b"%b\n#\n%b\n\n%b" % (
        regenerate_command.encode("utf-8"),
        lockfile_metadata_header(invalidation_digest, interpreter_constraints_str),
        content,
    )


def lockfile_metadata_header(invalidation_digest: str, interpreter_constraints: list[str]) -> bytes:
    """Produces a metadata bytes object for including at the top of a lockfile.

    Currently, this only consists of an invalidation digest for the file, which is used when Pants
    consumes the lockfile during builds.
    """

    metadata = {
        "invalidation_digest": invalidation_digest,
        "valid_interpreter_constraints": interpreter_constraints,
    }
    metadata_str = json.dumps(
        metadata,
        ensure_ascii=True,
        indent=2,
    )
    metadata_as_comment = "\n".join(f"# {i}" for i in metadata_str.splitlines())

    return (
        b"""
%(BEGIN_LOCKFILE_HEADER)b
%(metadata_as_comment)s
%(END_LOCKFILE_HEADER)b
    """
        % {
            b"BEGIN_LOCKFILE_HEADER": BEGIN_LOCKFILE_HEADER,
            b"metadata_as_comment": metadata_as_comment.encode("ascii"),
            b"END_LOCKFILE_HEADER": END_LOCKFILE_HEADER,
        }
    ).strip()


def read_lockfile_metadata(contents: bytes) -> LockfileMetadata:
    """Reads through `contents`, and returns the contents of the lockfile metadata block as a
    `LockfileMetadata` object."""

    def yield_metadata_lines() -> Iterable[bytes]:
        in_metadata_block = False
        for line in contents.splitlines():
            if line == BEGIN_LOCKFILE_HEADER:
                in_metadata_block = True
            elif line == END_LOCKFILE_HEADER:
                break
            elif in_metadata_block:
                yield line[2:]

    metadata_lines = b"\n".join(yield_metadata_lines())

    try:
        metadata = json.loads(metadata_lines)
    except json.decoder.JSONDecodeError:
        # If this block is invalid, this should trigger error/warning behavior
        metadata = {}

    T = TypeVar("T")

    def c(t: Callable[[Any], T], k: str) -> T | None:
        v = metadata.get(k, None)
        try:
            return t(v) if v is not None else None
        except Exception:
            # TODO: this should trigger error/warning behavior
            return None

    return LockfileMetadata(
        invalidation_digest=c(str, "invalidation_digest"),
        valid_interpreter_constraints=c(InterpreterConstraints, "valid_interpreter_constraints"),
    )
