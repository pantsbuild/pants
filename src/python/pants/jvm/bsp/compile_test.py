# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.fs import FileEntry
from pants.engine.internals.native_engine import FileDigest
from pants.jvm.bsp.compile import _first_occurrence_file_entries


def _fe(path: str, fingerprint_byte: str = "0") -> FileEntry:
    return FileEntry(
        path=path,
        file_digest=FileDigest(fingerprint=fingerprint_byte * 64, serialized_bytes_length=1),
    )


def test_first_occurrence_keeps_first_on_path_collision() -> None:
    """Two classpath entries with the same resource path → the merged result
    contains exactly one copy, from the first entry. Mirrors JVM classpath
    semantics where the first occurrence on the classpath wins.

    Before this dedup, `merge_digests(MergeDigests(...))` raised
    `IntrinsicError: Can only merge Directories with no duplicates` on this
    input — which fails BSP compile of any target whose closure has multiple
    modules each contributing the same resource path (e.g. multiple
    `logback.xml` files across first-party JVM modules in one BSP target).
    """
    first = [_fe("META-INF/logback.xml", "a")]
    second = [_fe("META-INF/logback.xml", "b")]

    kept = _first_occurrence_file_entries([first, second])

    assert len(kept) == 1
    assert kept[0].path == "META-INF/logback.xml"
    # First-occurrence wins: digest from `first`, not `second`.
    assert kept[0].file_digest.fingerprint.startswith("a")


def test_first_occurrence_preserves_distinct_paths() -> None:
    first = [_fe("a/x.class", "a")]
    second = [_fe("b/y.class", "b")]

    kept = _first_occurrence_file_entries([first, second])

    assert sorted(e.path for e in kept) == ["a/x.class", "b/y.class"]


def test_first_occurrence_handles_empty_input() -> None:
    assert _first_occurrence_file_entries([]) == []
    assert _first_occurrence_file_entries([[], []]) == []


def test_first_occurrence_drops_non_file_entries() -> None:
    """Symlinks and Directories that show up in DigestEntries are dropped —
    they're either re-created as implicit parents by CreateDigest, or simply
    not produced by JVM compile output.
    """
    file_entry = _fe("a/x.class", "a")
    not_a_file = object()  # stand-in for SymlinkEntry / Directory

    kept = _first_occurrence_file_entries([[not_a_file, file_entry]])

    assert kept == [file_entry]
