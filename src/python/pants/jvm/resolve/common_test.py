# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from unittest import mock

import pytest

from pants.engine.fs import EMPTY_DIGEST
from pants.jvm.resolve.common import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    CoursierResolveKey,
)

_coord1 = Coordinate("test", "art1", "1.0.0")
_coord2 = Coordinate("test", "art2", "1.0.0")
_coord3 = Coordinate("test", "art3", "1.0.0")
_coord4 = Coordinate("test", "art4", "1.0.0")
_coord5 = Coordinate("test", "art5", "1.0.0")


@pytest.mark.parametrize(
    "coordinate,transitive,expected",
    [
        (_coord1, False, {_coord1}),
        (_coord2, False, {_coord2, _coord3}),
        (_coord2, True, {_coord2, _coord5, _coord4, _coord3, _coord1}),
    ],
)
def test_lockfile_filter(
    coordinate: Coordinate, transitive: bool, expected: set[Coordinate]
) -> None:
    # No dependencies (coord1)
    # 1 direct dependency, more transitive dependencies (coord2)
    # 1 where direct dependencies provide no transitive dependencies (coord 4)
    # 1 where direct dependencies provide repeated dependencies (coord5)
    direct = {
        _coord1: set(),
        _coord2: {_coord3},  # 1, 2, 3, 4, 5
        _coord3: {_coord1, _coord4, _coord5},  # 1, 3, 4, 5
        _coord4: {_coord1},  # 1, 4
        _coord5: {_coord1, _coord4},  # 1, 4, 5
    }

    # Calculate transitive deps
    transitive_helper = {(i, k) for i, j in direct.items() for k in j}
    while True:
        old_len = len(transitive_helper)
        transitive_helper |= {(i, k) for i, j in transitive_helper for k in direct[j]}
        if old_len == len(transitive_helper):
            break
    transitive_deps = defaultdict(set)
    for (i, j) in transitive_helper:
        transitive_deps[i].add(j)

    lockfile = CoursierResolvedLockfile(
        entries=tuple(
            CoursierLockfileEntry(
                coord=coord,
                file_name=f"{coord.artifact}.jar",
                direct_dependencies=Coordinates(direct[coord]),
                dependencies=Coordinates(transitive_deps[coord]),
                file_digest=mock.Mock(),
            )
            for coord in direct
        )
    )

    key = CoursierResolveKey("example", "example.json", EMPTY_DIGEST)
    root, deps = (
        lockfile.dependencies(key, coordinate)
        if transitive
        else lockfile.direct_dependencies(key, coordinate)
    )
    result = sorted(i.coord for i in (root, *deps))
    assert result == sorted(expected)
