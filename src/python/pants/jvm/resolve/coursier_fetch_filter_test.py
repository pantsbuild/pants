# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import DefaultDict, Sequence
from unittest import mock

import pytest

from pants.engine.fs import EMPTY_DIGEST
from pants.jvm.resolve.common import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.key import CoursierResolveKey

coord1 = Coordinate("test", "art1", "1.0.0")
coord2 = Coordinate("test", "art2", "1.0.0")
coord3 = Coordinate("test", "art3", "1.0.0")
coord4 = Coordinate("test", "art4", "1.0.0")
coord5 = Coordinate("test", "art5", "1.0.0")


# No dependencies (coord1)
# 1 direct dependency, more transitive dependencies (coord2)
# 1 where direct dependencies provide no transitive dependencies (coord 4)
# 1 where direct dependencies provide repeated dependencies (coord5)
direct: dict[Coordinate, set[Coordinate]] = {
    coord1: set(),
    coord2: {
        coord3,
    },  # 1, 2, 3, 4, 5
    coord3: {coord1, coord4, coord5},  # 1, 3, 4, 5
    coord4: {
        coord1,
    },  # 1, 4
    coord5: {coord1, coord4},  # 1, 4, 5
}


@pytest.fixture
def lockfile() -> CoursierResolvedLockfile:
    # Calculate transitive deps
    transitive_ = {(i, k) for i, j in direct.items() for k in j}
    while True:
        old_len = len(transitive_)
        transitive_ |= {(i, k) for i, j in transitive_ for k in direct[j]}
        if old_len == len(transitive_):
            break
    transitive = DefaultDict(set)
    for i, j in transitive_:
        transitive[i].add(j)

    entries = (
        CoursierLockfileEntry(
            coord=coord,
            file_name=f"{coord.artifact}.jar",
            direct_dependencies=Coordinates(direct[coord]),
            dependencies=Coordinates(transitive[coord]),
            file_digest=mock.Mock(),
        )
        for coord in direct
    )

    return CoursierResolvedLockfile(entries=tuple(entries))


def test_no_deps(lockfile: CoursierResolvedLockfile) -> None:
    filtered = filter(coord1, lockfile, False)
    assert filtered == [coord1]


def test_filter_non_transitive_includes_direct_deps(lockfile: CoursierResolvedLockfile) -> None:
    filtered = filter(coord2, lockfile, False)
    assert filtered == [coord2, coord3]


def test_filter_transitive_includes_transitive_deps(lockfile: CoursierResolvedLockfile) -> None:
    filtered = filter(coord2, lockfile, True)
    assert set(filtered) == {coord1, coord2, coord3, coord4, coord5}
    # Entries should only appear once.
    assert len(filtered) == 5


def filter(coordinate, lockfile, transitive) -> Sequence[Coordinate]:
    key = CoursierResolveKey("example", "example.json", EMPTY_DIGEST)
    root, deps = (
        lockfile.dependencies(key, coordinate)
        if transitive
        else lockfile.direct_dependencies(key, coordinate)
    )
    return [i.coord for i in (root, *deps)]
