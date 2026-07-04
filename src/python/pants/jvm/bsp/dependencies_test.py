# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.internals.native_engine import FileDigest
from pants.jvm.bsp.dependencies import _sources_jar_basename, get_entry_for_coord
from pants.jvm.resolve.coordinate import SOURCES_CLASSIFIER, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile


def _entry(
    group: str, artifact: str, version: str, classifier: str | None = None
) -> CoursierLockfileEntry:
    return CoursierLockfileEntry(
        coord=Coordinate(group=group, artifact=artifact, version=version, classifier=classifier),
        file_name=f"{group}_{artifact}_{version}.jar",
        direct_dependencies=Coordinates(()),
        dependencies=Coordinates(()),
        file_digest=FileDigest(fingerprint="0" * 64, serialized_bytes_length=0),
    )


def test_get_entry_for_coord_matches_exact() -> None:
    """Sanity check: a perfectly matching lookup still works."""
    lockfile = CoursierResolvedLockfile(
        entries=(_entry("org.scala-lang", "scala-library", "2.13.18"),)
    )
    coord = Coordinate(group="org.scala-lang", artifact="scala-library", version="2.13.18")
    entry = get_entry_for_coord(lockfile, coord)
    assert entry is not None
    assert entry.coord.artifact == "scala-library"


def test_get_entry_for_coord_returns_none_for_unknown_artifact() -> None:
    lockfile = CoursierResolvedLockfile(
        entries=(_entry("org.scala-lang", "scala-library", "2.13.18"),)
    )
    coord = Coordinate(group="com.example", artifact="missing", version="1.0")
    assert get_entry_for_coord(lockfile, coord) is None


def test_get_entry_for_coord_matches_on_group_artifact_classifier_ignoring_version() -> None:
    """Coursier resolves a single version per (group, artifact, classifier) and
    may coerce upward when a transitive dep requires a newer version than the
    BUILD pins. The lockfile records the resolved version; an exact-equality
    lookup against the BUILD-declared version would silently drop the entry.

    Mirror the existing dedup key used by
    `CoursierResolvedLockfile.{direct_dependencies,dependencies}` so the
    lookup finds the lockfile entry regardless of the BUILD-declared version.
    """
    lockfile = CoursierResolvedLockfile(
        entries=(_entry("org.scala-lang", "scala-library", "2.13.18"),)
    )
    # BUILD declares 2.13.12; lockfile resolved to 2.13.18.
    coord = Coordinate(group="org.scala-lang", artifact="scala-library", version="2.13.12")
    entry = get_entry_for_coord(lockfile, coord)
    assert entry is not None, "Version-coerced lookup should still find the lockfile entry"
    assert entry.coord.version == "2.13.18"


def test_get_entry_for_coord_distinguishes_classifier() -> None:
    """A classifier-less coord should not match a sources-classifier entry."""
    lockfile = CoursierResolvedLockfile(
        entries=(
            _entry("org.scala-lang", "scala-library", "2.13.18", classifier=SOURCES_CLASSIFIER),
        )
    )
    binary_coord = Coordinate(group="org.scala-lang", artifact="scala-library", version="2.13.18")
    assert get_entry_for_coord(lockfile, binary_coord) is None


def test_sources_jar_basename_pairs_with_binary_via_libraryPrefix() -> None:
    """The IntelliJ-Scala BSP plugin (`bsp-builtin/.../BspResolverLogic.scala`)
    pairs source jars to binaries by stripping `.jar`, `-sources`/`-src`,
    `-javadoc` from the full canonical path and grouping by the result, with
    `sourcesSuffixes.exists(fileName.contains)` selecting the source jar.

    For the pairing to succeed:
      1. the source basename must contain literal `-sources` (not `_sources_`);
      2. after stripping `-sources.jar`, the source's full path must equal the
         binary's full path with `.jar` stripped.

    `classpath_dest_filename` produces the binary as
    `{group}_{artifact}_{version}.jar`; this function produces the matching
    source name.
    """
    coord = Coordinate(group="dev.zio", artifact="zio_2.13", version="2.1.14")
    basename = _sources_jar_basename(coord)

    assert basename == "dev.zio_zio_2.13_2.1.14-sources.jar"
    # Property 1: contains literal `-sources`.
    assert "-sources" in basename
    # Property 2: stripping `-sources.jar` yields the binary basename minus `.jar`.
    binary_stem = f"{coord.group}_{coord.artifact}_{coord.version}"
    assert basename.removesuffix("-sources.jar") == binary_stem
